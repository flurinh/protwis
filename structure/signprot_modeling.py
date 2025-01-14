from protein.models import Protein, ProteinConformation, ProteinSegment, ProteinFamily
from residue.models import Residue
from structure.models import *
from structure.functions import update_template_source, compare_and_update_template_source
from common.alignment import GProteinAlignment
from common.definitions import *
from signprot.models import SignprotComplex
import structure.structural_superposition as sp
from structure.homology_modeling_functions import GPCRDBParsingPDB

import Bio.PDB as PDB
from collections import OrderedDict
import pprint
from io import StringIO
import math
from copy import deepcopy


gprotein_segments = ProteinSegment.objects.filter(proteinfamily='Alpha')
gprotein_segment_slugs = [i.slug for i in gprotein_segments]
atom_num_dict = {'E':9, 'S':6, 'Y':12, 'G':4, 'A':5, 'V':7, 'M':8, 'L':8, 'I':8, 'T':7, 'F':11, 'H':10, 'K':9, 
                         'D':8, 'C':6, 'R':11, 'P':7, 'Q':9, 'N':8, 'W':14, '-':0}
subfam_template_preference = {'Gs': ['Gs','Gi/o','Gq/11','G12/13','GPa1 family'],
                              'Gi/o': ['Gi/o','Gq/11','G12/13','Gs','GPa1 family'],
                              'Gq/11': ['Gq/11','Gi/o','G12/13','Gs','GPa1 family'],
                              'G12/13': ['G12/13','Gq/11','Gi/o','Gs','GPa1 family'],
                              'GPa1': ['GPa1 family','Gi/o','Gq/11','G12/13','Gs']}

class SignprotModeling():
    def __init__(self, main_structure, signprot, template_source, trimmed_residues, alignment, main_pdb_array, debug=False):
        self.main_structure = main_structure
        self.signprot = signprot
        self.template_source = template_source
        self.trimmed_residues = trimmed_residues
        self.a = alignment
        self.main_pdb_array = main_pdb_array
        self.target_signprot = None
        self.debug = debug

    @staticmethod
    def get_alpha_templates(only_full=False):
        sc_all = SignprotComplex.objects.all().values_list('structure', flat=True)
        sep_all = StructureExtraProteins.objects.filter(structure__in=sc_all, category='G alpha')
        if only_full:
            sep_filtered = sep_all.filter(wt_coverage__gte=85)
        else:
            sep_filtered = sep_all
        return sep_filtered, sep_filtered.values_list('structure', flat=True)

    @staticmethod
    def group_alpha_templates(templates, group_by_subfam=False):
        template_dict = OrderedDict()
        for i in templates:
            if group_by_subfam:
                if i.wt_protein.family.parent not in template_dict:
                    template_dict[i.wt_protein.family.parent] = [i.structure]
                else:
                    template_dict[i.wt_protein.family.parent].append(i.structure)
            else:
                if i.wt_protein.family not in template_dict:
                    template_dict[i.wt_protein.family] = [i.structure]
                else:
                    template_dict[i.wt_protein.family].append(i.structure)
        for i, j in template_dict.items():
            j = sorted(j, key=lambda x: x.resolution)
            template_dict[i] = j
        return template_dict

    def find_h_domain_template(self, signprot, templates):
        template_dict = self.group_alpha_templates(templates)
        if signprot.family in template_dict:
            return template_dict[signprot.family][0]
        else:
            subfam_dict = self.group_alpha_templates(templates, group_by_subfam=True)
            if signprot.family.parent in subfam_dict:
                return subfam_dict[signprot.family.parent][0]
            else:
                return Structure.objects.get(pdb_code__index='3SN6')

    def get_ordered_alpha_templates(self, signprot):
        target_subfam = signprot.family.parent
        template_dict = self.group_alpha_templates(self.get_alpha_templates()[0], True)
        template_pool = []
        for subfam in subfam_template_preference[target_subfam.name]:
            subfam_obj = ProteinFamily.objects.get(name=subfam)
            if subfam_obj in template_dict:
                for t in template_dict[subfam_obj]:
                    template_pool.append(t)
        return template_pool

    def run(self):
        parse = GPCRDBParsingPDB()
        self.signprot_complex = SignprotComplex.objects.get(structure=self.main_structure)
        structure_signprot = self.signprot_complex.protein
        if self.signprot!=False:
            self.target_signprot = Protein.objects.get(entry_name=self.signprot)
        else:
            self.target_signprot = self.signprot_complex.protein
        self.signprot_protconf = ProteinConformation.objects.get(protein=self.target_signprot)
        sign_a = GProteinAlignment()
        sign_a.run_alignment(self.target_signprot, structure_signprot)
        signprot_pdb_array = parse.create_g_alpha_pdb_array(self.signprot_complex)
        
        # Alignment exception in HN for 6OIJ, shifting alignment by 6 residues
        if self.main_structure.pdb_code.index=='6OIJ':
            keys = list(signprot_pdb_array['HN'].keys())
            new_HN = OrderedDict()
            for i, k in enumerate(signprot_pdb_array['HN']):
                if i<8:
                    new_HN[k] = 'x'
                else:
                    new_HN[k] = signprot_pdb_array['HN'][keys[i-6]]
            signprot_pdb_array['HN'] = new_HN

        new_array = OrderedDict()

        # Initiate complex part of template source
        source_resis = Residue.objects.filter(protein_conformation__protein=self.target_signprot)
        for res in source_resis:
            if res.protein_segment.slug not in self.template_source:
                self.template_source[res.protein_segment.slug] = OrderedDict()
            if res.protein_segment.category=='loop':
                self.template_source[res.protein_segment.slug][str(res.sequence_number)] = [None, None]
            else:
                self.template_source[res.protein_segment.slug][res.display_generic_number.label] = [self.main_structure, self.main_structure]

        # Superimpose missing regions H1 - hfs2
        alt_complex_struct = None
        alt_signprot_complex = None
        segs_for_alt_complex_struct = []
        alt_templates_H_domain = self.get_alpha_templates(True)

        if self.main_structure.id not in alt_templates_H_domain[1]:
            segs_for_alt_complex_struct = ['H1', 'h1ha', 'HA', 'hahb', 'HB', 'hbhc', 'HC', 'hchd', 'HD', 'hdhe', 'HE', 'hehf', 'HF', 'hfs2']
            alt_complex_struct = self.find_h_domain_template(self.target_signprot, alt_templates_H_domain[0]) #Structure.objects.get(pdb_code__index='3SN6')
            alt_signprot_complex = SignprotComplex.objects.get(structure=alt_complex_struct)
            alt_signprot_pdb_array = parse.create_g_alpha_pdb_array(alt_signprot_complex)
            before_cgns = ['G.HN.50', 'G.HN.51', 'G.HN.52', 'G.HN.53']
            after_cgns =  ['G.H5.03', 'G.H5.04', 'G.H5.05', 'G.H5.06']
            orig_residues1 = parse.fetch_residues_from_array(signprot_pdb_array['HN'], before_cgns)
            orig_residues2 = parse.fetch_residues_from_array(signprot_pdb_array['H5'], after_cgns)
            orig_residues = parse.add_two_ordereddict(orig_residues1, orig_residues2)

            alt_residues1 = parse.fetch_residues_from_array(alt_signprot_pdb_array['HN'], before_cgns)
            alt_residues2 = parse.fetch_residues_from_array(alt_signprot_pdb_array['H5'], after_cgns)
            
            alt_middle = OrderedDict()
            for s in segs_for_alt_complex_struct:
                alt_middle = parse.add_two_ordereddict(alt_middle, alt_signprot_pdb_array[s])
                self.template_source = update_template_source(self.template_source, list(self.template_source[s].keys()), alt_complex_struct, s)

            alt_residues = parse.add_two_ordereddict(parse.add_two_ordereddict(alt_residues1, alt_middle), alt_residues2)
            del_list = []
            for r, t in alt_middle.items():
                if t=='x':
                    del_list.append(r)
            for r in del_list:
                del alt_residues[r]
            
            superpose = sp.LoopSuperpose(orig_residues, alt_residues)
            new_residues = superpose.run()
            key_list = list(new_residues.keys())[4:-4]
            for key in key_list:
                seg = key.split('.')[1]
                if key in signprot_pdb_array[seg] and signprot_pdb_array[seg][key]!='x':
                    continue
                signprot_pdb_array[seg][key] = new_residues[key]
            
            # alt local loop alignment
            alt_sign_a = GProteinAlignment()
            alt_sign_a.run_alignment(self.target_signprot, alt_signprot_complex.protein, segments=segs_for_alt_complex_struct)
            for alt_seg in segs_for_alt_complex_struct:
                sign_a.reference_dict[alt_seg] = alt_sign_a.reference_dict[alt_seg]
                sign_a.template_dict[alt_seg] = alt_sign_a.template_dict[alt_seg]
                sign_a.alignment_dict[alt_seg] = alt_sign_a.alignment_dict[alt_seg]

            # fix h1ha and hahb and hbhc
            if self.target_signprot.entry_name!='gnas2_human':
                h1ha = Residue.objects.filter(protein_conformation__protein=alt_signprot_complex.protein, protein_segment__slug='h1ha')
                h1ha_dict, hahb_dict = OrderedDict(), OrderedDict()
                for h in h1ha:
                    h1ha_dict[h.generic_number.label] = 'x'
                signprot_pdb_array['h1ha'] = h1ha_dict
                right_order = sorted(list(signprot_pdb_array['hahb'].keys()), key=lambda x: (x))
                for r in right_order:
                    hahb_dict[r] = signprot_pdb_array['hahb'][r]
                signprot_pdb_array['hahb'] = hahb_dict
                
            # Let Modeller model buffer regions
            self.trimmed_residues.append('s1h1_6')
            self.trimmed_residues.append('hfs2_1')
            self.trimmed_residues.append('hfs2_2')
            self.trimmed_residues.append('hfs2_3')
            self.trimmed_residues.append('hfs2_4')
            self.trimmed_residues.append('hfs2_5')
            self.trimmed_residues.append('hfs2_6')
            self.trimmed_residues.append('hfs2_7')
            self.trimmed_residues.append('G.S2.01')
            self.trimmed_residues.append('G.S2.02')
            self.trimmed_residues.append('s4h3_4')
            self.trimmed_residues.append('s4h3_5')

        # New loop alignments for signprot. If length differs between ref and temp, buffer is created in the middle of the loop
        loops = [i.slug for i in ProteinSegment.objects.filter(proteinfamily='Alpha', category='loop')]
        loops_to_model = []
        for r_seg, t_seg, a_seg in zip(sign_a.reference_dict, sign_a.template_dict, sign_a.alignment_dict):
            if r_seg in loops:
                loop_length = len(sign_a.reference_dict[r_seg])
                ref_loop = [i for i in list(sign_a.reference_dict[r_seg].values()) if i not in ['x','-']]
                ref_keys = [i for i in list(sign_a.reference_dict[r_seg].keys()) if i not in ['x','-']]
                ref_loop_residues = Residue.objects.filter(protein_conformation__protein=self.target_signprot, protein_segment__slug=r_seg)
                temp_loop = [i for i in list(sign_a.template_dict[t_seg].values()) if i not in ['x','-']]
                temp_keys = [i for i in list(sign_a.template_dict[t_seg].keys()) if i not in ['x','-']]
                if alt_complex_struct and r_seg in segs_for_alt_complex_struct:
                    temp_loop_residues = Residue.objects.filter(protein_conformation__protein=alt_signprot_complex.protein, protein_segment__slug=r_seg)
                else:
                    temp_loop_residues = Residue.objects.filter(protein_conformation__protein=structure_signprot, protein_segment__slug=r_seg)
                ref_out, temp_out, align_out = OrderedDict(), OrderedDict(), OrderedDict()
                # ref is longer
                if len(ref_loop)>len(temp_loop):
                    mid_temp = math.ceil(len(temp_loop)/2)
                    j = 0
                    for i in range(0, loop_length):
                        key = r_seg+'_'+str(i+1)
                        if i+1<=mid_temp:
                            temp_out[key] = temp_loop[i]
                            self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, i, ref_loop_residues[i].display_generic_number.label, 
                                                                                      ref_loop_residues[i].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                        elif mid_temp<i+1<=loop_length-mid_temp+1:
                            if i+1==loop_length-mid_temp+1 and len(temp_loop)%2==0:
                                temp_out[key] = temp_loop[mid_temp+j]
                                self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, mid_temp+j, ref_loop_residues[i].display_generic_number.label, 
                                                                                          ref_loop_residues[i].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                                j+=1
                            else:
                                temp_out[key.replace('_','?')] = '-'
                                self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, mid_temp+j, ref_loop_residues[i].display_generic_number.label, 
                                                                                          ref_loop_residues[i].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                        else:
                            temp_out[key] = temp_loop[mid_temp+j]
                            self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, mid_temp+j, ref_loop_residues[i].display_generic_number.label, 
                                                                                      ref_loop_residues[i].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                            j+=1
                    for i, j in enumerate(list(sign_a.reference_dict[r_seg].values())):
                        key = r_seg+'_'+str(i+1)
                        try:
                            temp_out[key]
                            ref_out[key] = j
                        except:
                            ref_out[key.replace('_','?')] = j
                        i+=1
                # temp is longer
                elif len(ref_loop)<len(temp_loop):
                    mid_ref = math.ceil(len(ref_loop)/2)
                    j = 0
                    for i in range(0, loop_length):
                        key = r_seg+'_'+str(i+1)
                        if i+1<=mid_ref:
                            ref_out[key] = ref_loop[i]
                            self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, i, temp_loop_residues[i].display_generic_number.label, 
                                                                                      ref_loop_residues[i].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                        elif mid_ref<i+1<=loop_length-mid_ref+1:
                            if i+1==loop_length-mid_ref+1 and len(ref_loop)%2==0:
                                ref_out[key] = ref_loop[mid_ref+j]
                                self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, mid_ref+j, temp_loop_residues[i].display_generic_number.label, 
                                                                                          ref_loop_residues[mid_ref+j].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                                j+=1
                            else:
                                ref_out[key.replace('_','?')] = '-'
                                self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, mid_ref+j, temp_loop_residues[i].display_generic_number.label, 
                                                                                          ref_loop_residues[mid_ref+j].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                        else:
                            ref_out[key] = ref_loop[mid_ref+j]
                            self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, mid_ref+j, temp_loop_residues[i].display_generic_number.label, 
                                                                                      ref_loop_residues[mid_ref+j].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                            j+=1
                    for i, j in enumerate(list(sign_a.template_dict[t_seg].values())):
                        key = r_seg+'_'+str(i+1)
                        try:
                            ref_out[key]
                            temp_out[key] = j
                        except:
                            temp_out[key.replace('_','?')] = j
                        i+=1
                    loops_to_model.append(r_seg)
                # ref and temp length equal
                else:
                    cr, ct = 1,1
                    for i, j in zip(list(sign_a.reference_dict[r_seg].values()), list(sign_a.template_dict[t_seg].values())):
                        ref_out[r_seg+'_'+str(cr)] = i
                        temp_out[r_seg+'_'+str(ct)] = j
                        self.template_source = compare_and_update_template_source(self.template_source, r_seg, signprot_pdb_array, ct-1, temp_loop_residues[ct-1].display_generic_number.label, 
                                                                                  ref_loop_residues[cr-1].sequence_number, segs_for_alt_complex_struct, alt_complex_struct, self.main_structure)
                        if i!='-':
                            cr+=1
                        if j!='-':
                            ct+=1
                        
                c = 1

                # update alignment dict
                for i, j in zip(list(ref_out.values()), list(temp_out.values())):
                    key = r_seg+'_'+str(c)
                    if i=='-' or j=='-':
                        align_out[key.replace('_','?')] = '-'
                    elif i!=j:
                        align_out[key] = '.'
                    elif i==j:
                        align_out[key] = i
                    c+=1
                # update pdb array
                new_pdb_array = OrderedDict()
                atoms_list = list(signprot_pdb_array[t_seg].values())
                j = 0
                for t_c, t in temp_out.items():
                    jplus1 = False
                    if t!='-':
                        for i in range(j, len(atoms_list)):
                            if atoms_list[j]!='-':
                                new_pdb_array[t_c] = atoms_list[j]
                                jplus1 = True
                                break
                        if jplus1:
                            j+=1
                    else:
                        new_pdb_array[t_c] = 'x'
                        # j+=1

                # pprint.pprint(new_pdb_array)
                # for i,j in new_pdb_array.items():
                #     try:
                #         print(i, PDB.Polypeptide.three_to_one(j[0].get_parent().get_resname()))
                #     except:
                #         print(i, j)

                # update dictionary keys with '?' if no backbone template
                ref_out_final, temp_out_final, align_out_final, new_pdb_array_final = OrderedDict(), OrderedDict(), OrderedDict(), OrderedDict()
                # self.template_source[r_seg] = OrderedDict()
                for i,j in new_pdb_array.items():
                    if '?' not in i and j=='x':
                        ref_out_final[i.replace('_','?').replace('.','?')] = ref_out[i]
                        temp_out_final[i.replace('_','?').replace('.','?')] = temp_out[i]
                        align_out_final[i.replace('_','?').replace('.','?')] = align_out[i]
                        new_pdb_array_final[i.replace('_','?').replace('.','?')] = new_pdb_array[i]
                    else:
                        ref_out_final[i] = ref_out[i]
                        temp_out_final[i] = temp_out[i]
                        align_out_final[i] = align_out[i]
                        new_pdb_array_final[i] = new_pdb_array[i]
                sign_a.reference_dict[r_seg] = ref_out_final
                sign_a.template_dict[t_seg] = temp_out_final
                sign_a.alignment_dict[a_seg] = align_out_final
                signprot_pdb_array[r_seg] = new_pdb_array_final
                
                align_loop = list(sign_a.alignment_dict[a_seg].values())

        # Updating template dict with pdb_array
        for seg, resis in signprot_pdb_array.items():
            for cgn, atoms in resis.items():
                if len(atoms)>1 and PDB.Polypeptide.three_to_one(atoms[0].get_parent().get_resname())!=sign_a.template_dict[seg][cgn]:
                    sign_a.template_dict[seg][cgn] = PDB.Polypeptide.three_to_one(atoms[0].get_parent().get_resname())
                    if sign_a.template_dict[seg][cgn]!=sign_a.reference_dict[seg][cgn]:
                        sign_a.alignment_dict[seg][cgn] = '.'
                elif atoms=='x':
                    sign_a.alignment_dict[seg][cgn] = 'x'


        # Rotamer switching
        rotamer_templates = self.get_ordered_alpha_templates(self.target_signprot)
        if self.debug:
            print("Signprot rotamer switching")
            print(rotamer_templates)
        for seg, resis in sign_a.alignment_dict.items():
            for cgn, pos in resis.items():
                if pos=='.':
                    for alt_temp in rotamer_templates:
                        ref_AA = sign_a.reference_dict[seg][cgn]
                        new_coords = self.non_conserved_switcher(cgn, ref_AA, signprot_pdb_array[seg][cgn], alt_temp)
                        if not new_coords:
                            continue
                        signprot_pdb_array[seg][cgn] = new_coords
                        sign_a.alignment_dict[seg][cgn] = ref_AA
                        self.template_source = update_template_source(self.template_source, [cgn], alt_temp, seg, just_rot=True)
                        if self.debug:
                            print(cgn, alt_temp, new_coords)
                        break
                    # If no alternative rotamer template, cut back to 5 atoms
                    signprot_pdb_array[seg][cgn] = [i for i in signprot_pdb_array[seg][cgn] if str(i.get_id()) in ['N','CA','C','O','CB']]
                    if self.debug:
                        print("No rotamer template, mutating to ALA: ", cgn)
        
        self.a.reference_dict = deepcopy(self.a.reference_dict)
        self.a.template_dict = deepcopy(self.a.template_dict)
        self.a.alignment_dict = deepcopy(self.a.alignment_dict)

        for seg, values in sign_a.reference_dict.items():
            new_array[seg] = OrderedDict()
            # self.template_source[seg] = OrderedDict()
            final_values = deepcopy(values)
            for key, res in values.items():
                try:
                    if signprot_pdb_array[seg][key]=='x':
                        new_array[seg][key] = 'x'
                        self.template_source = update_template_source(self.template_source, [key], None, seg)
                    else:
                        new_array[seg][key] = signprot_pdb_array[seg][key]
                except:
                    if res!='-':
                        new_array[seg][key] = '-'
                        self.template_source = update_template_source(self.template_source, [key], None, seg)
            self.a.reference_dict[seg] = final_values
        for seg, values in sign_a.template_dict.items():
            for key, res in values.items():
                if new_array[seg][key]=='x':
                    sign_a.template_dict[seg][key] = 'x'
                else:
                    if new_array[seg][key]=='-':
                        sign_a.template_dict[seg][key] = '-'
                    else:
                        pdb_res = PDB.Polypeptide.three_to_one(new_array[seg][key][0].get_parent().get_resname())
                        if pdb_res!=sign_a.template_dict[seg][key]:
                            sign_a.template_dict[seg][key] = pdb_res
            self.a.template_dict[seg] = sign_a.template_dict[seg]

        for seg, values in sign_a.alignment_dict.items():
            for key, res in values.items():
                if new_array[seg][key]=='x':
                    values[key] = 'x'
            self.a.alignment_dict[seg] = values
        signprot_pdb_array = new_array

        for seg, values in signprot_pdb_array.items():
            self.main_pdb_array[seg] = values

        delete_HN_begin = []
        for i in self.a.reference_dict['HN']:
            if i=='G.HN.30':
                break
            delete_HN_begin.append(i)

        for d in delete_HN_begin:
            del self.a.reference_dict['HN'][d]
            try:
                del self.a.template_dict['HN'][d]
            except:
                pass
            try:
                del self.a.alignment_dict['HN'][d]
            except:
                pass
            del self.main_pdb_array['HN'][d]
            try:
                del self.template_source['HN'][d]
            except:
                pass

        # add residues to model to self.trimmed_residues
        gprot_segments = [i.slug for i in ProteinSegment.objects.filter(proteinfamily='Alpha')]
        for i,j in self.a.reference_dict.items():
            if i in gprot_segments:
                for k,l in j.items():
                    if '?' in k or self.main_pdb_array[i][k] in ['-','x']:
                        self.trimmed_residues.append(k)
                    if i in loops_to_model:
                        self.trimmed_residues.append(k)

        # custom mods
        long_HG_prots = Protein.objects.filter(family__name='Gs')
        if structure_signprot in long_HG_prots and self.target_signprot not in long_HG_prots:
            self.trimmed_residues.append('G.HG.08')
            self.trimmed_residues.append('G.HG.09')
            self.trimmed_residues.append('G.HG.12')
            self.trimmed_residues.append('G.HG.13')
            self.trimmed_residues.append('G.HG.14')
            self.trimmed_residues.append('G.HG.16')
            self.trimmed_residues.append('G.HG.17')
        if structure_signprot!=self.target_signprot or (alt_signprot_complex and alt_signprot_complex.protein not in [None, self.target_signprot]):
            # hbhc
            hbhc_keys = list(self.a.reference_dict['hbhc'].keys())
            self.trimmed_residues.append(hbhc_keys[2])
            self.trimmed_residues.append(hbhc_keys[3])
            self.trimmed_residues.append(hbhc_keys[-3])
            self.trimmed_residues.append(hbhc_keys[-2])
            # H1
            self.trimmed_residues.append('G.H1.07')
            self.trimmed_residues.append('G.H1.08')
        if 'hgh4' in loops_to_model:
            self.trimmed_residues.append('G.H4.01')
            self.trimmed_residues.append('G.H4.02')
            self.trimmed_residues.append('G.H4.03')

        # Add mismatching residues to trimmed residues for modeling
        for seg, val in self.a.alignment_dict.items():
            if seg in gprotein_segment_slugs:
                for key, res in val.items():
                    if res=='.':
                        self.trimmed_residues.append(key)
        # Add residues with missing atom coordinates to trimmed residues for modeling
        for seg, val in self.main_pdb_array.items():
            if seg in gprotein_segment_slugs:
                for key, atoms in val.items():
                    if atoms not in ['-','x']:
                        if atom_num_dict[PDB.Polypeptide.three_to_one(atoms[0].get_parent().get_resname())]>len(atoms):
                            self.trimmed_residues.append(key)

        # Add Beta and Gamma chains
        p = PDB.PDBParser(QUIET=True).get_structure('structure', StringIO(self.main_structure.pdb_data.pdb))[0]
        beta = p[self.signprot_complex.beta_chain]
        gamma = p[self.signprot_complex.gamma_chain]
        self.a.reference_dict['Beta'] = OrderedDict()
        self.a.template_dict['Beta'] = OrderedDict()
        self.a.alignment_dict['Beta'] = OrderedDict()
        self.main_pdb_array['Beta'] = OrderedDict()
        self.template_source['Beta'] = OrderedDict()
        self.a.reference_dict['Gamma'] = OrderedDict()
        self.a.template_dict['Gamma'] = OrderedDict()
        self.a.alignment_dict['Gamma'] = OrderedDict()
        self.main_pdb_array['Gamma'] = OrderedDict()
        self.template_source['Gamma'] = OrderedDict()
        for b_res in beta:
            key = str(b_res.get_id()[1])
            self.a.reference_dict['Beta'][key] = PDB.Polypeptide.three_to_one(b_res.get_resname())
            self.a.template_dict['Beta'][key] = PDB.Polypeptide.three_to_one(b_res.get_resname())
            self.a.alignment_dict['Beta'][key] = PDB.Polypeptide.three_to_one(b_res.get_resname())
            atoms = [atom for atom in b_res]
            self.main_pdb_array['Beta'][key] = atoms
            self.template_source['Beta'][key] = [self.main_structure, self.main_structure]
        for g_res in gamma:
            key = str(g_res.get_id()[1])
            self.a.reference_dict['Gamma'][key] = PDB.Polypeptide.three_to_one(g_res.get_resname())
            self.a.template_dict['Gamma'][key] = PDB.Polypeptide.three_to_one(g_res.get_resname())
            self.a.alignment_dict['Gamma'][key] = PDB.Polypeptide.three_to_one(g_res.get_resname())
            atoms = [atom for atom in g_res]
            self.main_pdb_array['Gamma'][key] = atoms
            self.template_source['Gamma'][key] = [self.main_structure, self.main_structure]

        # for i,j,k,l in zip(sign_a.reference_dict, sign_a.template_dict, sign_a.alignment_dict, signprot_pdb_array):
        #     pprint.pprint(self.template_source[i])
        #     for v,b,n,m in zip(sign_a.reference_dict[i], sign_a.template_dict[j], sign_a.alignment_dict[k], signprot_pdb_array[l]):
        #         print(v, b, n, m, sign_a.reference_dict[i][v], sign_a.template_dict[j][b], sign_a.alignment_dict[k][n], signprot_pdb_array[l][m])
        # raise AssertionError

    def non_conserved_switcher(self, cgn, AA, ref_atoms, template):
        try:
            print(cgn, template, AA, ref_atoms[0].get_parent().get_resname())
            rot = Rotamer.objects.get(structure=template, residue__display_generic_number__label=cgn)
            print(rot.residue.amino_acid)
            if rot.residue.amino_acid!=AA or rot.missing_atoms:
                return False
            parse = GPCRDBParsingPDB()
            parsed_atoms = parse.parse_rotamer_pdb(rot)
            superpose = sp.RotamerSuperpose(ref_atoms, parsed_atoms)
            new_atoms = superpose.run()
            if self.debug:
                print(template, cgn, superpose.backbone_rmsd)
            if superpose.backbone_rmsd>0.45:
                return False
            return new_atoms
        except Exception as msg:
            if self.debug:
                print("WARNING: Rotamer swap-in {} at {} failed with {}".format(template, cgn, msg))
            return False


