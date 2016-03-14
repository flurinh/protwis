from django.core.management.base import BaseCommand

from protein.models import Protein, ProteinSegment, ProteinConformation, ProteinAnomaly, ProteinState
from residue.models import Residue
from structure.models import * #Structure, PdbData, Rotamer, StructureModel, StructureModelLoopTemplates, StructureModelAnomalies, StructureModelResidues, StructureSegment, StructureSegmentModeling
from common.alignment import Alignment, AlignedReferenceTemplate
import structure.structural_superposition as sp
import structure.assign_generic_numbers_gpcr as as_gn
#from structure.calculate_RMSD import Validation

import Bio.PDB as PDB
from modeller import *
from modeller.automodel import *
from collections import OrderedDict
import os
import logging
import numpy as np
from io import StringIO
import sys
import multiprocessing
import pprint
import re
from datetime import datetime


startTime = datetime.now()
l = multiprocessing.Lock()

def homology_model_multiprocessing(receptor):
    Homology_model = HomologyModeling(receptor, 'Inactive', ['Inactive'])
    alignment = Homology_model.run_alignment()
    if alignment!=None:
        Homology_model.build_homology_model(alignment)#, switch_bulges=False, switch_constrictions=False, switch_rotamers=False)    
#        Homology_model.upload_to_db()
        logger = logging.getLogger('homology_modeling')
        l.acquire()
        logger.info('Model for {} successfully built.'.format(receptor))
        l.release()
        
class Command(BaseCommand):    
    def handle(self, *args, **options):
        Homology_model = HomologyModeling('gpr3_human', 'Inactive', ['Inactive'])
        alignment = Homology_model.run_alignment()
        Homology_model.build_homology_model(alignment)
#        receptor_list = ['gp151_human', 
#                         'gpr37_human', 'gp176_human', 'gpr19_human', 'p2ry8_human', 
#                         'p2y10_human']
#        if os.path.isfile('./logs/homology_modeling.log'):
#            os.remove('./logs/homology_modeling.log')
#        logger = logging.getLogger('homology_modeling')
#        hdlr = logging.FileHandler('./logs/homology_modeling.log')
#        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
#        hdlr.setFormatter(formatter)
#        logger.addHandler(hdlr) 
#        logger.setLevel(logging.INFO)        
#        
#        pool = multiprocessing.Pool(processes=multiprocessing.cpu_count())
#        for i in receptor_list:
#            pool.apply_async(homology_model_multiprocessing, [i])           
#        pool.close()
#        pool.join()

        print('\n###############################')
        print('Total runtime: ',datetime.now() - startTime)
        print('###############################\n')
        

class HomologyModeling(object):
    ''' Class to build homology models for GPCRs. 
    
        @param reference_entry_name: str, protein entry name \n
        @param state: str, endogenous ligand state of reference \n
        @param query_states: list, list of endogenous ligand states to be applied for template search, 
        default: same as reference
    '''
    segment_coding = {1:'TM1',2:'TM2',3:'TM3',4:'TM4',5:'TM5',6:'TM6',7:'TM7'}
    def __init__(self, reference_entry_name, state, query_states):
        self.reference_entry_name = reference_entry_name
        self.state = state
        self.query_states = query_states
        self.statistics = CreateStatistics(self.reference_entry_name)
        self.reference_protein = Protein.objects.get(entry_name=self.reference_entry_name)
        self.uniprot_id = self.reference_protein.accession
        self.reference_sequence = self.reference_protein.sequence
        self.reference_class = self.reference_protein.family.parent.parent.parent
        self.statistics.add_info('uniprot_id',self.uniprot_id)
        self.segments = []
        self.similarity_table = OrderedDict()
        self.similarity_table_all = OrderedDict()
        self.main_structure = None
        self.main_template_preferred_chain = ''
        self.loop_template_table = OrderedDict()
        self.loops = OrderedDict()
        self.logger = logging.getLogger('homology_modeling')
        l.acquire()
        self.logger.info('Building model for {} {}.'.format(self.reference_protein, self.state))
        l.release()        
        
    def __repr__(self):
        return "<{}, {}>".format(self.reference_entry_name, self.state)

    def upload_to_db(self):
        # upload StructureModel        
        state=ProteinState.objects.get(name=self.state)
        hommod, created = StructureModel.objects.update_or_create(protein=self.reference_protein, state=state, 
                                                                  main_template=self.main_structure, 
                                                                  pdb=self.format_final_model())
                                                                  
        # upload StructureModelLoopTemplates
        for loop,template in self.statistics.info_dict['loops'].items():
            seg = ProteinSegment.objects.get(slug=loop[:4])
            try:
                StructureModelLoopTemplates.objects.update_or_create(homology_model=hommod,template=template,segment=seg)
            except:
                pass
            
        # upload StructureModelAnomalies
        ref_bulges = self.statistics.info_dict['reference_bulges']
        temp_bulges = self.statistics.info_dict['template_bulges']
        ref_const = self.statistics.info_dict['reference_constrictions']
        temp_const = self.statistics.info_dict['template_constrictions']
                
        # upload StructureModelResidues
        
        for gn, res in self.statistics.info_dict['conserved_residues'].items():
            if gn[0] not in ['E','I']:
                res = Residue.objects.get(protein_conformation__protein=self.reference_protein, 
                                          generic_number__label=gn)
                res_temp = Residue.objects.get(protein_conformation=self.main_structure.protein_conformation, 
                                               generic_number__label=gn)
                rotamer = Rotamer.objects.filter(structure=self.main_structure, residue=res_temp)
            else:
                res = Residue.objects.filter(protein_conformation__protein=self.reference_protein, 
                                             protein_segment__slug=gn.split('|')[0])[int(gn.split('|')[1])-1]
                if gn[0] in ['E','I'] and gn[:4]+"_dis" in self.statistics.info_dict['loops'].keys():
                    alt_temp = self.statistics.info_dict['loops'][gn[:4]+"_dis"]
                    res_temp = Residue.objects.filter(protein_conformation=alt_temp.protein_conformation, 
                                                  protein_segment__slug=gn.split('|')[0])[int(gn.split('|')[1])-1]
                    rotamer = Rotamer.objects.filter(structure=alt_temp, residue=res_temp)
                else:
                    res_temp = Residue.objects.filter(protein_conformation=self.main_structure.protein_conformation, 
                                                  protein_segment__slug=gn.split('|')[0])[int(gn.split('|')[1])-1]
                    rotamer = Rotamer.objects.filter(structure=self.main_structure, residue=res_temp)                          
            rotamer = self.right_rotamer_select(rotamer)
            if gn[0] in ['E','I'] and gn[:4]+"_dis" in self.statistics.info_dict['loops'].keys():
                alt_temp = self.statistics.info_dict['loops'][gn[:4]+"_dis"]
                StructureModelResidues.objects.update_or_create(homology_model=hommod, sequence_number=res.sequence_number,
                                                                residue=res, rotamer=rotamer, template=alt_temp,
                                                                origin='conserved', segment=res.protein_segment)
            else:
                StructureModelResidues.objects.update_or_create(homology_model=hommod, sequence_number=res.sequence_number,
                                                                residue=res, rotamer=rotamer, template=self.main_structure,
                                                                origin='conserved', segment=res.protein_segment)
        for gn, temp in self.statistics.info_dict['non_conserved_residue_templates'].items():
            res = Residue.objects.get(protein_conformation__protein=self.reference_protein, generic_number__label=gn)
            res_temp = Residue.objects.get(protein_conformation=temp.protein_conformation,
                                           generic_number__label=gn)
            rotamer = Rotamer.objects.filter(structure=temp, residue=res_temp)
            rotamer = self.right_rotamer_select(rotamer)
            StructureModelResidues.objects.update_or_create(homology_model=hommod, sequence_number=res.sequence_number, 
                                                            residue=res, rotamer=rotamer, template=temp, 
                                                            origin='switched', segment=res.protein_segment)
        for gn in self.statistics.info_dict['trimmed_residues']:
            if gn[0] not in ['E','I']:
                gn = gn.replace('.','x')
                res = Residue.objects.get(protein_conformation__protein=self.reference_protein, 
                                          generic_number__label=gn)
            else:
                gn = gn.replace('?','|')
                res = Residue.objects.filter(protein_conformation__protein=self.reference_protein, 
                                             protein_segment__slug=gn.split('|')[0])[int(gn.split('|')[1])-1]
            StructureModelResidues.objects.update_or_create(homology_model=hommod, sequence_number=res.sequence_number,
                                                            residue=res, rotamer__isnull=True, template__isnull=True,
                                                            origin='free', segment=res.protein_segment)
                                   
    def right_rotamer_select(self, rotamer):
        if len(rotamer)>1:
            for i in rotamer:
                if i.pdbdata.pdb.startswith('COMPND')==False:
                    rotamer = i
                    break
        else:
            rotamer=rotamer[0]
        return rotamer
                                                            
    def format_final_model(self):
        self.starting_res_num = list(Residue.objects.filter(protein_segment=2, 
                                     protein_conformation__protein=self.reference_protein))[0].sequence_number
        resnum = self.starting_res_num
        with open ('./structure/homology_models/{}_{}/modeller_test.pdb'.format(self.uniprot_id, self.state), 'r+') as f:
            pdblines = f.readlines()
            out_list = []
            prev_num = 1
            for line in pdblines:
                try:
                    pdb_re = re.search('(ATOM[A-Z\s\d]+\S{3}\s+)(\d+)([A-Z\s\d.-]+)',line)
                    if int(pdb_re.group(2))>prev_num:
                        resnum+=1
                        prev_num = int(pdb_re.group(2))
                    whitespace = (len(str(resnum))-len(pdb_re.group(2)))*-1
                    if whitespace==0:
                        out_line = pdb_re.group(1)+str(resnum)+pdb_re.group(3)
                    else:
                        out_line = pdb_re.group(1)[:whitespace]+str(resnum)+pdb_re.group(3)
                    out_list.append(out_line)
                except:
                    out_list.append(line)
#            io = StringIO(''.join(out_list))
#            pdb_struct = PDB.PDBParser(PERMISSIVE=True).get_structure('structure', io)[0]
#            assign_gn = as_gn.GenericNumbering(structure=pdb_struct)
#            pdb_struct = assign_gn.assign_generic_numbers()
#            assign_gn.save_gn_to_pdb()
#            outio = PDB.PDBIO()
#            outio.set_structure(pdb_struct)
#            outio.save('./structure/homology_models/{}_{}/modeller_test_ready.pdb'.format(self.uniprot_id, self.state))
#        with open('./structure/homology_models/{}_{}/modeller_test_GPCRDB.pdb'.format(self.uniprot_id, self.state),'r+') as f:
#            pdbdata = f.read()
        return ''.join(out_list)


    def fetch_struct_helix_ends_from_db(self, structure):
        ''' Returns structure's helix end generic numbers after updating them with annotated data.
        '''
        raw = StructureSegment.objects.filter(structure=structure)
        annotated = StructureSegmentModeling.objects.filter(structure=structure)
        ends = OrderedDict()
        for i in raw:
            if i.protein_segment.slug[0]=='T':
                while Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=i.start).generic_number==None:
                    i.start+=1
                s = Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=i.start)
                while Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=i.end).generic_number==None:
                    i.end-=1
                e = Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=i.end)
                ends[s.protein_segment.slug] = [s.generic_number.label,e.generic_number.label]
        for j in annotated:
            if j.protein_segment.slug[0]=='T':
                if j.start!=0:
                    while Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=j.start).generic_number==None:
                        j.start+=1
                    sa = Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=j.start)
                    ends[j.protein_segment.slug][0] = sa.generic_number.label
                if j.end!=0:
                    while Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=j.end).generic_number==None:
                        j.end-=1
                    ea = Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=j.end)
                    ends[j.protein_segment.slug][1] = ea.generic_number.label
        return ends      

    def fetch_struct_helix_ends_from_array(self, array):
        ''' Returns helix ends from structure array (GPCRDBParsingPDB.pdb_array_creator()).
        '''
        ends = OrderedDict()
        for seg_lab, seg in array.items():
            if seg_lab[0]=='T':
                ends[seg_lab] = [list(seg.keys())[0].replace('.','x'),list(seg.keys())[-1].replace('.','x')]
        return ends
        
    def correct_helix_ends(self, main_structure, main_pdb_array, a):
        ''' Updates main template structure with annotated helix ends, if helix is too long, it removes residues, if it
            is too short, it superpositions residues from next closest template. Updates alignment with changes.
        '''
        raw_helix_ends = self.fetch_struct_helix_ends_from_array(main_pdb_array)
        anno_helix_ends = self.fetch_struct_helix_ends_from_db(main_structure)
        parser = GPCRDBParsingPDB()
        for raw_seg, anno_seg in zip(raw_helix_ends, anno_helix_ends):
            s_dif = parser.gn_comparer(raw_helix_ends[raw_seg][0],anno_helix_ends[anno_seg][0],main_structure.protein_conformation)
            e_dif = parser.gn_comparer(raw_helix_ends[raw_seg][1],anno_helix_ends[anno_seg][1],main_structure.protein_conformation)
            if s_dif<0:
                s_gn = Residue.objects.get(protein_conformation=main_structure.protein_conformation, generic_number__label=raw_helix_ends[raw_seg][0])
                seq_nums = [i for i in range(s_gn.sequence_number,s_gn.sequence_number-s_dif)]
                gns = [j.generic_number.label for j in list(Residue.objects.filter(protein_conformation=main_structure.protein_conformation, sequence_number__in=seq_nums))]
                for gn in gns:
                    a.template_dict[raw_seg][gn]='x'
                    a.alignment_dict[raw_seg][gn]='x'
            if e_dif>0:
                e_gn = Residue.objects.get(protein_conformation=main_structure.protein_conformation, generic_number__label=raw_helix_ends[raw_seg][1])
                seq_nums = [i for i in range(e_gn.sequence_number-e_dif+1,e_gn.sequence_number+1)]
                gns = [j.generic_number.label for j in list(Residue.objects.filter(protein_conformation=main_structure.protein_conformation, sequence_number__in=seq_nums))]
                for gn in gns:
                    a.template_dict[raw_seg][gn]='x'
                    a.alignment_dict[raw_seg][gn]='x'
        self.helix_ends = raw_helix_ends

        modifications = {'added':{'TM1':[[],[]],'TM2':[[],[]],'TM3':[[],[]],'TM4':[[],[]],'TM5':[[],[]],'TM6':[[],[]],'TM7':[[],[]], 'H8':[[],[]]},
                         'removed':{'TM1':[[],[]],'TM2':[[],[]],'TM3':[[],[]],'TM4':[[],[]],'TM5':[[],[]],'TM6':[[],[]],'TM7':[[],[]], 'H8':[[],[]]}}
        for ref_seg, temp_seg, align_seg in zip(a.reference_dict, a.template_dict, a.alignment_dict):
            mid = len(a.reference_dict[ref_seg])/2
            for ref_res, temp_res, align_res in zip(a.reference_dict[ref_seg],a.template_dict[temp_seg],a.alignment_dict[align_seg]):
                if a.reference_dict[ref_seg][ref_res]=='x':
                    if list(a.reference_dict[ref_seg].keys()).index(ref_res)<mid:    
                        modifications['removed'][ref_seg][0].append(ref_res)
                    else:
                        modifications['removed'][ref_seg][1].append(ref_res)
                    del a.reference_dict[ref_seg][ref_res]
                    del a.template_dict[temp_seg][temp_res]
                    del a.alignment_dict[align_seg][align_res]
                    del main_pdb_array[ref_seg][ref_res.replace('x','.')]
                elif a.template_dict[temp_seg][temp_res]=='x':
                    if list(a.template_dict[temp_seg].keys()).index(temp_res)<mid:    
                        modifications['added'][temp_seg][0].append(temp_res)
                    else:
                        modifications['added'][temp_seg][1].append(temp_res)
            if ref_seg[0]=='T':
                if len(modifications['added'][ref_seg][0])>0:
                    self.helix_ends[ref_seg][0] = modifications['added'][ref_seg][0][0]
                if len(modifications['added'][ref_seg][1])>0:
                    self.helix_ends[ref_seg][1] = modifications['added'][ref_seg][1][-1]               
                if len(modifications['removed'][ref_seg][0])>0:
                    self.helix_ends[ref_seg][0] = parser.gn_indecer(modifications['removed'][ref_seg][0][-1], 'x', 1)
                if len(modifications['removed'][ref_seg][1])>0:
                    self.helix_ends[ref_seg][1] = parser.gn_indecer(modifications['removed'][ref_seg][1][0], 'x', -1)
                if len(modifications['added'][ref_seg][0])>0:
                    for struct in self.similarity_table:
                        if struct!=main_structure:
                            alt_helix_ends = self.fetch_struct_helix_ends_from_db(struct)
                            try:
                                if parser.gn_comparer(alt_helix_ends[ref_seg][0],self.helix_ends[ref_seg][0],struct.protein_conformation)<=0:
                                    all_keys = list(a.reference_dict[ref_seg].keys())[:len(modifications['added'][ref_seg][0])+4]
                                    ref_keys = [i for i in all_keys if i not in modifications['added'][ref_seg][0]]
                                    reference = parser.fetch_residues_from_pdb(main_structure,ref_keys)
                                    template = parser.fetch_residues_from_pdb(struct,all_keys)
                                    superpose = sp.OneSidedSuperpose(reference,template,4,0)
                                    sup_residues = superpose.run()
                                    new_residues = OrderedDict()
                                    for gn, atoms in sup_residues.items():
                                        if gn.replace('.','x') not in ref_keys:
                                            new_residues[gn] = atoms
                                    for gn, atoms in main_pdb_array[ref_seg].items():
                                        gn_ = gn.replace('.','x')
                                        new_residues[gn] = atoms
                                        a.template_dict[temp_seg][gn_] = PDB.Polypeptide.three_to_one(
                                                                         atoms[0].get_parent().get_resname())
                                        if a.template_dict[temp_seg][gn_]==a.reference_dict[ref_seg][gn_]:
                                            a.alignment_dict[ref_seg][gn_] = a.reference_dict[ref_seg][gn_]
                                        else:
                                            a.alignment_dict[ref_seg][gn_] = '.'
                                    main_pdb_array[ref_seg] = new_residues
                                    break
                            except:
                                pass
                if len(modifications['added'][ref_seg][1])>0:
                    for struct in self.similarity_table:
                        if struct!=main_structure:
                            alt_helix_ends = self.fetch_struct_helix_ends_from_db(struct)
                            try:
                                if parser.gn_comparer(alt_helix_ends[ref_seg][1],self.helix_ends[ref_seg][1],struct.protein_conformation)>=0:
                                    all_keys = list(a.reference_dict[ref_seg].keys())[-1*(len(modifications['added'][ref_seg][1])+4):]
                                    ref_keys = [i for i in all_keys if i not in modifications['added'][ref_seg][1]]
                                    reference = parser.fetch_residues_from_pdb(main_structure,ref_keys)
                                    template = parser.fetch_residues_from_pdb(struct,all_keys)
                                    superpose = sp.OneSidedSuperpose(reference,template,4,1)
                                    sup_residues = superpose.run()
                                    new_residues = OrderedDict()
                                    for gn, atoms in sup_residues.items():
                                        if gn.replace('.','x') not in ref_keys:
                                            new_residues[gn]=atoms
                                    for gn, atoms in new_residues.items():
                                        gn_ = gn.replace('.','x')
                                        if gn_ in modifications['added'][ref_seg][1]:
                                            main_pdb_array[ref_seg][gn] = atoms
                                            a.template_dict[ref_seg][gn_] = PDB.Polypeptide.three_to_one(
                                                                            atoms[0].get_parent().get_resname())
                                            if a.template_dict[ref_seg][gn_]==a.reference_dict[ref_seg][gn_]:
                                                a.alignment_dict[ref_seg][gn_] = a.reference_dict[ref_seg][gn_]
                                            else:
                                                a.alignment_dict[ref_seg][gn_] = '.'
                                    break
                            except:
                                pass
        pprint.pprint(modifications)
        print(main_structure)
        return main_pdb_array, a
        
        
    def run_alignment(self, core_alignment=True, query_states='default', 
                      segments=['TM1','ICL1','TM2','ECL1','TM3','ICL2','TM4','ECL2','TM5','TM6','TM7','H8'], 
                      order_by='similarity'):
        ''' Creates pairwise alignment between reference and target receptor(s).
            Returns Alignment object.
            
            @param segments: list, list of segments to use, e.g.: ['TM1','ICL1','TM2','ECL1'] \n
            @param order_by: str, order results by identity, similarity or simscore
        '''
        if query_states=='default':
            query_states=self.query_states
        alignment = AlignedReferenceTemplate(self.reference_protein, segments, query_states, order_by)
        main_pdb_array = OrderedDict()
        if core_alignment==True:
            print('Alignment: ',datetime.now() - startTime)
            enhanced_alignment = alignment.enhance_best_alignment()
            print('Enhanced alignment: ',datetime.now() - startTime)
            if enhanced_alignment==None:
                return None
            self.segments = segments
            self.main_structure = alignment.main_template_structure           
            self.similarity_table = alignment.similarity_table
            self.similarity_table_all = self.run_alignment(core_alignment=False, 
                                                           query_states=['Inactive','Active'])[0].similarity_table
            self.main_template_preferred_chain = str(self.main_structure.preferred_chain)[0]
            self.statistics.add_info("main_template", self.main_structure)
            self.statistics.add_info("preferred_chain", self.main_template_preferred_chain)
            
            parse = GPCRDBParsingPDB()
            main_pdb_array = parse.pdb_array_creator(structure=self.main_structure)           
            end_correction = self.correct_helix_ends(self.main_structure, main_pdb_array, alignment)
            main_pdb_array = end_correction[0]
            alignment = end_correction[1]            
            
            for loop in ['ICL1','ECL1','ICL2','ECL2','ICL3','ECL3']:
                loop_alignment = AlignedReferenceTemplate(self.reference_protein, [loop], ['Inactive','Active'], 
                                                          order_by='similarity', 
                                                          provide_main_template_structure=self.main_structure,
                                                          provide_similarity_table=self.similarity_table_all,
                                                          main_pdb_array=main_pdb_array)
                self.loop_template_table[loop] = loop_alignment.loop_table
                try:
                    if loop in list(alignment.alignment_dict.keys()) and self.main_structure in loop_alignment.loop_table:
                        temp_loop_table = OrderedDict([('aligned',100)])
                        try:
                            for lab, val in loop_alignment.loop_table.items():
                                temp_loop_table[lab] = val
                            self.loop_template_table[loop] = temp_loop_table
                        except:
                            pass
                except:
                    pass
            self.statistics.add_info('similarity_table', self.similarity_table)
            self.statistics.add_info('loops',self.loop_template_table)
            print('Loop alignment: ',datetime.now() - startTime)
        return alignment, main_pdb_array
        
        
    def build_homology_model(self, ref_temp_alignment, switch_bulges=True, switch_constrictions=True, loops=True, 
                             switch_rotamers=True):
        ''' Function to identify and switch non conserved residues in the alignment. Optionally,
            it can identify and switch bulge and constriction sites too. 
            
            @param ref_temp_alignment: AlignedReferenceAndTemplate, alignment of reference and main template with 
            alignment string. \n
            @param switch_bulges: boolean, identify and switch bulge sites. Default = True.
            @param switch_constrictions: boolean, identify and switch constriction sites. Default = True.
        '''
        a = ref_temp_alignment[0]
        main_pdb_array = ref_temp_alignment[1]
        ref_bulge_list, temp_bulge_list, ref_const_list, temp_const_list = [],[],[],[]
        parse = GPCRDBParsingPDB()
        
        # loops
        if loops==True:
            loop_stat = OrderedDict()
#            print(self.loop_template_table)
            for label, structures in self.loop_template_table.items():
                loop = Loops(self.reference_protein, label, structures, self.main_structure)
                loop_template = loop.fetch_loop_residues(main_pdb_array)
                if type(loop.loop_output_structure)!=type([]):
                    loop_insertion = loop.insert_loop_to_arrays(loop.loop_output_structure, main_pdb_array, loop_template, 
                                                                a.reference_dict, a.template_dict, a.alignment_dict)
                else:
                    loop_insertion = loop.insert_ECL2_to_arrays(loop.loop_output_structure, main_pdb_array, loop_template,
                                                                a.reference_dict, a.template_dict, a.alignment_dict)
                main_pdb_array = loop_insertion.main_pdb_array
                a.reference_dict = loop_insertion.reference_dict
                a.template_dict = loop_insertion.template_dict
                a.alignment_dict = loop_insertion.alignment_dict
                if loop.new_label!=None:
                    loop_stat[loop.new_label] = loop.loop_output_structure
                else:
                    loop_stat[label] = loop.loop_output_structure
            self.statistics.add_info('loops', loop_stat)
            self.loops = loop_stat
        
#        print(self.main_structure)
        for i,j,k,l in zip(a.reference_dict,a.template_dict,a.alignment_dict,main_pdb_array):
            for q,w,e,r in zip(a.reference_dict[i],a.template_dict[j],a.alignment_dict[k],main_pdb_array[l]):
                print(q,a.reference_dict[i][q],w,a.template_dict[j][w],e,a.alignment_dict[k][e],r,main_pdb_array[l][r])   
#        pprint.pprint(a.reference_dict)
#        pprint.pprint(a.template_dict)
#        pprint.pprint(a.alignment_dict)
#        pprint.pprint(main_pdb_array)
        
        print('Integrate loops: ',datetime.now() - startTime)

        # bulges and constrictions
        if switch_bulges==True or switch_constrictions==True:
            for ref_seg, temp_seg, aligned_seg in zip(a.reference_dict, a.template_dict, a.alignment_dict):
                if ref_seg[0]=='T':
                    for ref_res, temp_res, aligned_res in zip(a.reference_dict[ref_seg], a.template_dict[temp_seg], 
                                                              a.alignment_dict[aligned_seg]):
                        gn = ref_res
                        gn_num = parse.gn_num_extract(gn, 'x')[1]
                        
                        if a.alignment_dict[aligned_seg][aligned_res]=='-':
                            if (a.reference_dict[ref_seg][ref_res]=='-' and 
                                a.reference_dict[ref_seg][parse.gn_indecer(gn,'x',-1)] not in 
                                ['-','/'] and a.reference_dict[ref_seg][parse.gn_indecer(gn,'x',+1)] not in ['-','/']): 
            
                                # bulge in template
                                if len(str(gn_num))==3:
                                    if switch_bulges==True:
                                        try:
                                            Bulge = Bulges(gn)
                                            bulge_template = Bulge.find_bulge_template(self.similarity_table_all, 
                                                                                       bulge_in_reference=False)
                                            bulge_site = OrderedDict([
                                                (parse.gn_indecer(gn,'x',-2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-2).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',-1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-1).replace('x','.')]),
                                                (gn.replace('x','.'), 
                                                 main_pdb_array[ref_seg][gn.replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+1).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+2).replace('x','.')])]) 
                                            superpose = sp.BulgeConstrictionSuperpose(bulge_site, bulge_template)
                                            new_residues = superpose.run()
                                            switch_res = 0
                                            for gen_num, atoms in bulge_template.items():
                                                if switch_res!=0 and switch_res!=3:
                                                    gn__ = gen_num.replace('.','x')
                                                    main_pdb_array[ref_seg][gen_num] = new_residues[gen_num]
                                                    a.template_dict[temp_seg][gn__] = PDB.Polypeptide.three_to_one(
                                                                                       atoms[0].get_parent().get_resname())
                                                    if a.template_dict[temp_seg][gn__]==a.reference_dict[ref_seg][gn__]:
                                                        a.alignment_dict[aligned_seg][gn__]=a.template_dict[temp_seg][gn__]
                                                    else:
                                                        a.alignment_dict[aligned_seg][gn__]='.'
                                                switch_res+=1
                                            del main_pdb_array[ref_seg][gn.replace('x','.')]
                                            del a.reference_dict[ref_seg][gn]
                                            del a.template_dict[temp_seg][gn]
                                            del a.alignment_dict[aligned_seg][gn]
                                            temp_bulge_list.append({gn:Bulge.template})
                                        except:
                                            temp_bulge_list.append({gn:None})
                                        
                                # constriction in reference
                                else:
                                    if switch_constrictions==True:
                                        try:
                                            Const = Constrictions(gn)
                                            constriction_template = Const.find_constriction_template(
                                                                                            self.similarity_table_all,
                                                                                            constriction_in_reference=True)
                                            constriction_site = OrderedDict([
                                                (parse.gn_indecer(gn,'x',-2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-2).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',-1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-1).replace('x','.')]),
                                                (gn.replace('x','.'), 
                                                 main_pdb_array[ref_seg][gn.replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+1).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+2).replace('x','.')])])                                      
                                            superpose = sp.BulgeConstrictionSuperpose(constriction_site, 
                                                                                      constriction_template)
                                            new_residues = superpose.run()                                  
                                            switch_res = 0
                                            for gen_num, atoms in constriction_template.items():
                                                if switch_res!=0 and switch_res!=3:
                                                    gn__ = gen_num.replace('.','x')
                                                    main_pdb_array[ref_seg][gen_num] = new_residues[gen_num]
                                                    a.template_dict[gn__] = PDB.Polypeptide.three_to_one(
                                                                                       atoms[0].get_parent().get_resname())
                                                    if a.template_dict[temp_seg][gn__]==a.reference_dict[ref_seg][gn__]:
                                                        a.alignment_dict[aligned_seg][gn__]=a.template_dict[temp_seg][gn__]
                                                switch_res+=1
                                            ref_const_list.append({gn:Const.template})
                                            del main_pdb_array[ref_seg][gn.replace('x','.')]
                                            del a.reference_dict[ref_seg][gn]
                                            del a.template_dict[temp_seg][gn]
                                            del a.alignment_dict[aligned_seg][gn]
                                        except:
                                            ref_const_list.append({gn:None})
                            elif (a.template_dict[ref_seg][temp_res]=='-' and 
                                  a.template_dict[temp_seg][parse.gn_indecer(gn,'x',-1)] not in 
                                  ['-','/'] and a.template_dict[temp_seg][parse.gn_indecer(gn,'x',+1)] not in ['-','/']): 
                                
                                # bulge in reference
                                if len(str(gn_num))==3:
                                    if switch_bulges==True:
                                        try:
                                            Bulge = Bulges(gn)
                                            bulge_template = Bulge.find_bulge_template(self.similarity_table_all,
                                                                                       bulge_in_reference=True)
                                            bulge_site = OrderedDict([
                                                (parse.gn_indecer(gn,'x',-2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-2).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',-1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-1).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+1).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+2).replace('x','.')])]) 
                                            superpose = sp.BulgeConstrictionSuperpose(bulge_site, bulge_template)
                                            new_residues = superpose.run()
                                            switch_res = 0
                                            for gen_num, atoms in bulge_template.items():
                                                if switch_res!=0 and switch_res!=4:
                                                    gn__ = gen_num.replace('.','x')
                                                    main_pdb_array[ref_seg][gen_num] = new_residues[gen_num]
                                                    a.template_dict[temp_seg][gn__] = PDB.Polypeptide.three_to_one(
                                                                                       atoms[0].get_parent().get_resname())
                                                    if a.template_dict[temp_seg][gn__]==a.reference_dict[ref_seg][gn__]:
                                                        a.alignment_dict[aligned_seg][gn__]=a.template_dict[temp_seg][gn__]
                                                switch_res+=1
                                            ref_bulge_list.append({gn:Bulge.template})
                                            if a.reference_dict[ref_seg][gn] == a.template_dict[temp_seg][gn]:
                                                a.alignment_dict[ref_seg][gn] = a.reference_dict[ref_seg][gn]
                                            else:
                                                a.alignment_dict[ref_seg][gn] = '.'
                                        except:
                                            ref_bulge_list.append({gn:None})
                                        
                                # constriction in template
                                else:
                                    if switch_constrictions==True:
                                        try:
                                            Const = Constrictions(gn)
                                            constriction_template = Const.find_constriction_template(
                                                                                           self.similarity_table_all,
                                                                                           constriction_in_reference=False)
                                            constriction_site = OrderedDict([
                                                (parse.gn_indecer(gn,'x',-2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-2).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',-1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',-1).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+1).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+1).replace('x','.')]),
                                                (parse.gn_indecer(gn,'x',+2).replace('x','.'), 
                                                 main_pdb_array[ref_seg][parse.gn_indecer(gn,'x',+2).replace('x','.')])]) 
                                            superpose = sp.BulgeConstrictionSuperpose(constriction_site, 
                                                                                      constriction_template)
                                            new_residues = superpose.run()
                                            switch_res = 0
                                            for gen_num, atoms in constriction_template.items():
                                                if switch_res!=0 and switch_res!=4:
                                                    gn__ = gen_num.replace('.','x')
                                                    main_pdb_array[ref_seg][gen_num] = new_residues[gen_num]
                                                    a.template_dict[temp_seg][gn__] = PDB.Polypeptide.three_to_one(
                                                                                       atoms[0].get_parent().get_resname())
                                                    if a.template_dict[temp_seg][gn__]==a.reference_dict[ref_seg][gn__]:
                                                        a.alignment_dict[aligned_seg][gn__]=a.template_dict[temp_seg][gn__]
                                                switch_res+=1
                                            temp_const_list.append({gn:Const.template})
                                            if a.reference_dict[ref_seg][gn] == a.template_dict[temp_seg][gn]:
                                                a.alignment_dict[ref_seg][gn] = a.reference_dict[ref_seg][gn]
                                            else:
                                                a.alignment_dict[ref_seg][gn] = '.'
                                        except:
                                            temp_const_list.append({gn:None})
                                        
            self.statistics.add_info('reference_bulges', ref_bulge_list)
            self.statistics.add_info('template_bulges', temp_bulge_list)
            self.statistics.add_info('reference_constrictions', ref_const_list)
            self.statistics.add_info('template_constrictions', temp_const_list)
            
            # insert bulge to array in the right place
            if ref_bulge_list!=[]:
                out_pdb_array = OrderedDict()
                bulge_gns = []
                for bulge in ref_bulge_list:
                    if list(bulge.values())[0]!=None:
                        gn = list(bulge.keys())[0].replace('x','.')
                        bulge_gns.append(gn)
                for seg_id, residues in main_pdb_array.items():
                    seg = OrderedDict()
                    for key, value in residues.items():
                        seg[key] = value                
                        if str(key)+'1' in bulge_gns:
                            seg[str(key)+'1'] = main_pdb_array[seg_id][str(key)+'1']
                    out_pdb_array[seg_id] = seg
                main_pdb_array = out_pdb_array
            
            if temp_const_list!=[]:
                out_pdb_array = OrderedDict()
                const_gns = []
                for const in temp_const_list:
                    if list(const.values())[0]!=None:
                        gn = list(const.keys())[0].replace('x','.')
                        const_gns.append(gn)
                for seg_id, residues in main_pdb_array.items():
                    seg = OrderedDict()
                    for key, value in residues.items():
                        seg[key] = value
                        if parse.gn_indecer(key, '.', +1) in const_gns:
                            seg[gn] = main_pdb_array[seg_id][gn]
                    out_pdb_array[seg_id] = seg
                main_pdb_array = out_pdb_array
        print('Integrate bulges/constrictions: ',datetime.now() - startTime)
        # check for inconsitencies with db
        pdb_db_inconsistencies = []
        for seg_label, segment in a.template_dict.items():
            try:
                for gn, res in segment.items():
                    try:
                        if res==PDB.Polypeptide.three_to_one(
                                            main_pdb_array[seg_label][gn.replace('x','.')][0].get_parent().get_resname()):
                            pass
                        elif 'x' in gn:
                            try:
                                Residue.objects.get(
                                        protein_conformation__protein=self.main_structure.protein_conformation.protein, 
                                        generic_number__label=gn)
                                pdb_db_inconsistencies.append({gn:a.template_dict[seg_label][gn]})
                            except:
                                pass
                    except:
                        pass
            except:
                pass
        
        if pdb_db_inconsistencies!=[]:
            for incons in pdb_db_inconsistencies:
                seg = self.segment_coding[int(list(incons.keys())[0][0])]
                seq_num = Residue.objects.get(
                                        protein_conformation__protein=self.main_structure.protein_conformation.protein, 
                                        generic_number__label=list(incons.keys())[0])
                temp_segment, temp_array = OrderedDict(), OrderedDict()
                for key, value in main_pdb_array[seg].items():
                    if key==str(seq_num.sequence_number):
                        temp_segment[list(incons.keys())[0].replace('x','.')] = value
                    else:
                        temp_segment[key] = value
                for seg_id, segment in main_pdb_array.items():
                    if seg_id==seg:
                        temp_array[seg_id] = temp_segment
                    else:
                        temp_array[seg_id] = segment
                main_pdb_array = temp_array
                a.template_dict[seg][list(incons.keys())[0]] = PDB.Polypeptide.three_to_one(
                            main_pdb_array[seg][list(incons.keys())[0].replace('x','.')][0].get_parent().get_resname())
                if a.reference_dict[seg][list(incons.keys())[0]]==a.template_dict[seg][list(incons.keys())[0]]:
                    a.alignment_dict[seg][list(incons.keys())[0]] = a.reference_dict[seg][list(incons.keys())[0]]
                 
        self.statistics.add_info('pdb_db_inconsistencies', pdb_db_inconsistencies)
        path = "./structure/homology_models/{}_{}/".format(self.uniprot_id,self.state)
        if not os.path.exists(path):
            os.mkdir(path)
        self.write_homology_model_pdb(
                                "./structure/homology_models/{}_{}/pre_switch.pdb".format(self.uniprot_id, self.state), 
                                main_pdb_array, a)        
        print('Check inconsistencies: ',datetime.now() - startTime)
        # inserting loops for free modeling
        for label, template in loop_stat.items():
            if template==None:
                modeling_loops = Loops(self.reference_protein, label, self.similarity_table_all, self.main_structure)
                modeling_loops.insert_gaps_for_loops_to_arrays(main_pdb_array, a.reference_dict, a.template_dict,
                                                               a.alignment_dict)
                main_pdb_array = modeling_loops.main_pdb_array
                a.reference_dict = modeling_loops.reference_dict
                a.template_dict = modeling_loops.template_dict
                a.alignment_dict = modeling_loops.alignment_dict
        print('Free loops: ',datetime.now() - startTime)
        # non-conserved residue switching
        if switch_rotamers==True:
            non_cons_switch = self.run_non_conserved_switcher(main_pdb_array,a.reference_dict,a.template_dict,
                                                              a.alignment_dict)
            main_pdb_array = non_cons_switch[0]
            a.reference_dict = non_cons_switch[1]
            a.template_dict = non_cons_switch[2]
            a.alignment_dict = non_cons_switch[3]
            trimmed_residues = non_cons_switch[4]
        else:
            trimmed_residues=[]
            for seg_id, seg in main_pdb_array.items():
                for key in seg:
                    if a.reference_dict[seg_id][str(key).replace('.','x')]!='-':
                        trimmed_residues.append(key)
        print('Rotamer switching: ',datetime.now() - startTime)

        # write to file
        path = "./structure/homology_models/{}_{}/".format(self.uniprot_id,self.state)
        if not os.path.exists(path):
            os.mkdir(path)
        trimmed_res_nums = self.write_homology_model_pdb(path+self.uniprot_id+"_post.pdb", main_pdb_array, 
                                                         a, trimmed_residues=trimmed_residues)                                                         
#        pprint.pprint(main_pdb_array)
#        pprint.pprint(a.reference_dict)
#        pprint.pprint(a.template_dict)
#        raise AssertionError()
                                                         
        # Model with MODELLER
        self.create_PIR_file(a, path+self.uniprot_id+"_post.pdb")
        self.run_MODELLER("./structure/PIR/"+self.uniprot_id+"_"+self.state+".pir", path+self.uniprot_id+"_post.pdb", 
                          self.uniprot_id, 1, "modeller_test.pdb", atom_dict=trimmed_res_nums)
        
        with open('./structure/homology_models/{}_Inactive/{}.stat.txt'.format(self.uniprot_id, self.uniprot_id), 'w') as stat_file:
            for label, info in self.statistics.items():
                stat_file.write('{} : {}\n'.format(label, info))
            
        print('MODELLER build: ',datetime.now() - startTime)
        pprint.pprint(self.statistics)
        print('################################')
        return self
    
    def run_non_conserved_switcher(self, main_pdb_array, reference_dict, template_dict, alignment_dict):
        ''' Switches non-conserved residues with best possible template. Returns refreshed main_pdb_array 
            (atom coordinates), reference_dict (reference generic numbers and residue ids), template_dict (template 
            generic numbers and residue ids) and alignment_dict (aligned reference and template dictionary). 
            
            @param main_pdb_array: nested OrderedDict(), output of GPCRDBParsingPDB().pdb_array_creator()
            @param reference_dict: reference dictionary of AlignedReferenceTemplate.
            @param template_dict: template dictionary of AlignedReferenceTemplate.
            @param alignment_dict: alignment dictionary of AlignedReferenceTemplate.
        '''
        parse = GPCRDBParsingPDB()
        ref_length = 0
        conserved_count = 0
        non_cons_count = 0
        trimmed_res_num = 0
        switched_count = 0
        non_cons_res_templates, conserved_residues = OrderedDict(), OrderedDict()
        trimmed_residues = []
        inconsistencies = []
        for incons in self.statistics.info_dict['pdb_db_inconsistencies']:
            inconsistencies.append(list(incons.keys())[0])
        
        for ref_seg, temp_seg, aligned_seg in zip(reference_dict, template_dict, alignment_dict):
            for ref_res, temp_res, aligned_res in zip(reference_dict[ref_seg], template_dict[temp_seg], 
                                                      alignment_dict[aligned_seg]):
                if reference_dict[ref_seg][ref_res]!='-':
                    ref_length+=1
                if template_dict[temp_seg][temp_res]=='x':
                    trimmed_residues.append(ref_res)
                    trimmed_res_num+=1
                    non_cons_count+=1
                if (ref_res not in inconsistencies and
                    alignment_dict[aligned_seg][aligned_res]!='.' and
                    alignment_dict[aligned_seg][aligned_res]!='x' and 
                    alignment_dict[aligned_seg][aligned_res]!='-'):
                    conserved_residues[ref_res] = alignment_dict[aligned_seg][aligned_res]
                    conserved_count+=1
                gn = ref_res    
                if (gn in inconsistencies or alignment_dict[aligned_seg][aligned_res]=='.' and 
                    reference_dict[ref_seg][gn]!=template_dict[temp_seg][gn]):
                    non_cons_count+=1
                    gn_ = str(ref_res).replace('x','.')
                    no_match = True
                    if '|' in gn_:
                        try:
                            list_num = int(gn.split('|')[1])-1                       
                            gn = list(Residue.objects.filter(protein_conformation__protein=self.reference_protein,
                                      protein_segment__slug=ref_seg.split('_')[0]))[list_num].generic_number.label
                            gn_ = gn.replace('x','.')
                        except:
                            pass
                    for struct in self.similarity_table:
                        try:
                            alt_temp = parse.fetch_residues_from_pdb(struct, [gn])
                            if reference_dict[ref_seg][ref_res]==PDB.Polypeptide.three_to_one(
                                                                    alt_temp[gn_][0].get_parent().get_resname()):
                                orig_res = main_pdb_array[ref_seg][str(ref_res).replace('x','.')]
                                alt_res = alt_temp[gn_]
                                superpose = sp.RotamerSuperpose(orig_res, alt_res)
                                new_atoms = superpose.run()
                                if superpose.backbone_rmsd>0.3:
                                    continue
                                main_pdb_array[ref_seg][str(ref_res).replace('x','.')] = new_atoms
                                template_dict[temp_seg][temp_res] = reference_dict[ref_seg][ref_res]
                                non_cons_res_templates[gn] = struct
                                switched_count+=1
                                no_match = False
                                break
                        except:
                            pass
                    if no_match==True:
                        try:
                            if 'free' not in ref_seg:
                                residue = main_pdb_array[ref_seg][str(ref_res).replace('x','.')]
                                main_pdb_array[ref_seg][str(ref_res).replace('x','.')] = residue[0:5]
                                trimmed_residues.append(gn_)
                                trimmed_res_num+=1
                            elif 'free' in ref_seg:
                                trimmed_residues.append(gn_)
                                trimmed_res_num+=1
                        except:
                            logging.warning("Missing atoms in {} at {}".format(self.main_structure,gn))

        self.statistics.add_info('ref_seq_length', ref_length)
        self.statistics.add_info('conserved_num', conserved_count)
        self.statistics.add_info('non_conserved_num', non_cons_count)
        self.statistics.add_info('trimmed_residues_num', trimmed_res_num)
        self.statistics.add_info('non_conserved_switched_num', switched_count)
        self.statistics.add_info('conserved_residues', conserved_residues)
        self.statistics.add_info('non_conserved_residue_templates', non_cons_res_templates)
        self.statistics.add_info('trimmed_residues', trimmed_residues)

        return [main_pdb_array, reference_dict, template_dict, alignment_dict, trimmed_residues]
    
    def write_homology_model_pdb(self, filename, main_pdb_array, ref_temp_alignment, trimmed_residues=[]):
        ''' Write PDB file from pdb array to file.
        
            @param filename: str, filename of output file \n
            @param main_pdb_array: OrderedDict(), of atoms of pdb, where keys are generic numbers/residue numbers and
            values are list of atoms. Output of GPCRDBParsingPDB.pdb_array_creator().
            @param ref_temp_alignment: AlignedReferenceAndTemplate, only writes residues that are in ref_temp_alignment.
        '''
        key = ''
#        self.starting_res_num = list(Residue.objects.filter(protein_segment=2, protein_conformation__protein=self.reference_protein))[0].sequence_number
#        res_num = self.starting_res_num-1
        res_num = 0
        atom_num = 0
        trimmed_resi_nums = OrderedDict()
        with open(filename,'w+') as f:
            for seg_id, segment in main_pdb_array.items():
                trimmed_segment = OrderedDict()
                for key in segment:
                    if str(key).replace('.','x') :#in ref_temp_alignment.reference_dict[seg_id]:
                        res_num+=1
#                        try:
#                            if segment[key] not in ['-','x'] and ref_temp_alignment.reference_dict[seg_id][key]=='-':
#                                res_num-=1
#                        except:
#                            pass
                        if key in trimmed_residues:
                            trimmed_segment[key] = res_num
                            if 'x' in segment[key]:
                                f.write("\nTER")
                            if '?' in key:
                                continue
                        if 'x' in segment[key]:
                            f.write("\nTER")
                            continue
                        if '?' in key and '-' in segment[key]:
                            continue
                        for atom in main_pdb_array[seg_id][key]: 
                            atom_num+=1
                            coord = list(atom.get_coord())
                            coord1 = "%8.3f"% (coord[0])
                            coord2 = "%8.3f"% (coord[1])
                            coord3 = "%8.3f"% (coord[2])
                            if str(atom.get_id())=='CA':
                                if len(key)==4:
                                    bfact = "%6.2f"% (float(key))
                                elif '.' not in key:
                                    bfact = "%6.2f"% (float(atom.get_bfactor()))
                                else:
                                    bfact = " -%4.2f"% (float(key))
                            else:
                                bfact = "%6.2f"% (float(atom.get_bfactor()))
                            occupancy = "%6.2f"% (atom.get_occupancy())
                            template="""
ATOM{atom_num}  {atom}{res} {chain}{res_num}{coord1}{coord2}{coord3}{occupancy}{bfactor}{atom_s}  """
                            context={"atom_num":str(atom_num).rjust(7), "atom":str(atom.get_id()).ljust(4),
                                     "res":atom.get_parent().get_resname(), 
                                     "chain":str(self.main_template_preferred_chain)[0],
                                     "res_num":str(res_num).rjust(4), "coord1":coord1.rjust(12), 
                                     "coord2":coord2.rjust(8), "coord3":coord3.rjust(8), 
                                     "occupancy":str(occupancy).rjust(3),
                                     "bfactor":str(bfact).rjust(4), "atom_s":str(str(atom.get_id())[0]).rjust(12)}
                            f.write(template.format(**context))
                trimmed_resi_nums[seg_id] = trimmed_segment
            f.write("\nTER\nEND")
        return trimmed_resi_nums
                    
    def create_PIR_file(self, ref_temp_alignment, template_file):
        ''' Create PIR file from reference and template alignment (AlignedReferenceAndTemplate).
        
            @param ref_temp_alignment: AlignedReferenceAndTemplate
            @template_file: str, name of template file with path
        '''
        ref_sequence, temp_sequence = '',''
        res_num = 0
        for ref_seg, temp_seg in zip(ref_temp_alignment.reference_dict, ref_temp_alignment.template_dict):
#            if ref_seg!='H8':
            for ref_res, temp_res in zip(ref_temp_alignment.reference_dict[ref_seg], 
                                         ref_temp_alignment.template_dict[temp_seg]):
                res_num+=1
                if ref_temp_alignment.reference_dict[ref_seg][ref_res]=='x':
                    ref_sequence+='-'
                else:
                    ref_sequence+=ref_temp_alignment.reference_dict[ref_seg][ref_res]
                if ref_temp_alignment.template_dict[temp_seg][temp_res]=='x':
                    temp_sequence+='-'
                else:
                    temp_sequence+=ref_temp_alignment.template_dict[temp_seg][temp_res]
        with open("./structure/PIR/"+self.uniprot_id+"_"+self.state+".pir", 'w+') as output_file:
            template="""
>P1;{temp_file}
structure:{temp_file}:1:{chain}:{res_num}:{chain}::::
{temp_sequence}*

>P1;{uniprot}
sequence:{uniprot}::::::::
{ref_sequence}*
            """
            context={"temp_file":template_file,
                     "chain":self.main_template_preferred_chain,
                     "res_num":res_num,
                     "temp_sequence":temp_sequence,
                     "uniprot":self.uniprot_id,
                     "ref_sequence":ref_sequence}
            output_file.write(template.format(**context))
            
    def run_MODELLER(self, pir_file, template, reference, number_of_models, output_file_name, atom_dict=None):
        ''' Build homology model with MODELLER.
        
            @param pir_file: str, file name of PIR file with path \n
            @param template: str, file name of template with path \n
            @param reference: str, Uniprot code of reference sequence \n
            @param number_of_models: int, number of models to be built \n
            @param output_file_name: str, name of output file
        '''
        log.none()
        env = environ(rand_seed=80851) #!!random number generator
        
        if atom_dict==None:
            a = automodel(env, alnfile = pir_file, knowns = template, sequence = reference, 
                          assess_methods=(assess.DOPE))
        else:
            a = HomologyMODELLER(env, alnfile = pir_file, knowns = template, sequence = reference, 
                                 assess_methods=(assess.DOPE), atom_selection=atom_dict)
        
        a.starting_model = 1
        a.ending_model = number_of_models
        a.md_level = refine.slow
        path = "./structure/homology_models/{}".format(reference+"_"+self.state)
        if not os.path.exists(path):
            os.mkdir(path)
        a.make()

        # Get a list of all successfully built models from a.outputs
        ok_models = [x for x in a.outputs if x['failure'] is None]

        # Rank the models by DOPE score
        key = 'DOPE score'
        if sys.version_info[:2] == (2,3):
            # Python 2.3's sort doesn't have a 'key' argument
            ok_models.sort(lambda a,b: cmp(a[key], b[key]))
        else:
            ok_models.sort(key=lambda a: a[key])
        
        # Get top model
        m = ok_models[0]
#        print("Top model: %s (DOPE score %.3f)" % (m['name'], m[key]))        
        
        for file in os.listdir("./"):
            if file==m['name']:
                os.rename("./"+file, "./structure/homology_models/{}_{}/".format(self.uniprot_id,
                                                                                 self.state)+output_file_name)
            elif file.startswith(self.uniprot_id):
                os.remove("./"+file)#, "./structure/homology_models/{}_{}/".format(self.uniprot_id,self.state)+file)


class SilentModeller(object):
    def __enter__(self):
        self._stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')

    def __exit__(self, *args):
        sys.stdout.close()
        sys.stdout = self._stdout

        
class HomologyMODELLER(automodel):
    def __init__(self, env, alnfile, knowns, sequence, assess_methods, atom_selection):
        super(HomologyMODELLER, self).__init__(env, alnfile=alnfile, knowns=knowns, sequence=sequence, 
                                               assess_methods=assess_methods)
        self.atom_dict = atom_selection
        
    def select_atoms(self):
        selection_out = []
        for seg_id, segment in self.atom_dict.items():
            for gn, atom in segment.items():
                selection_out.append(self.residues[str(atom)])
        return selection(selection_out)
        
    def make(self):
        with SilentModeller():
            super(HomologyMODELLER, self).make()


class Loops(object):
    ''' Class to handle loops in GPCR structures.
    '''
    def __init__(self, reference_protein, loop_label, loop_template_structures, main_structure):
        self.segment_order = OrderedDict([('TM1',1), ('ICL1',1.5), ('TM2',2), ('ECL1',2.5), ('TM3',3), ('ICL2',3.5), 
                                          ('TM4',4), ('ECL2',4.5), ('TM5',5), ('ICL3',5.5), ('TM6',6), ('ECL3',6.5), 
                                          ('TM7',7), ('H8',7.5)])
        self.reference_protein = reference_protein
        self.loop_label = loop_label
        self.loop_template_structures = loop_template_structures
        self.main_structure = main_structure
        self.loop_output_structure = None
        self.new_label = None
        self.aligned = False
    
    def fetch_loop_residues(self, main_pdb_array):
        ''' Fetch list of Atom objects of the loop when there is an available template. Returns an OrderedDict().
        '''
        if self.loop_template_structures!=None:
            parse = GPCRDBParsingPDB()            
            seg_list = list(self.segment_order.keys())
            prev_seg = seg_list[seg_list.index(self.loop_label)-1]
            next_seg = seg_list[seg_list.index(self.loop_label)+1]
            orig_before_gns = [i.replace('.','x') for i in list(main_pdb_array[prev_seg].keys())[-4:]]
            orig_after_gns = [j.replace('.','x') for j in list(main_pdb_array[next_seg].keys())[:4]]
            last_before_gn = orig_before_gns[-1]
            first_after_gn = orig_after_gns[0]
            if self.loop_label=='ECL2':
                try:
                    ref_res = Residue.objects.filter(protein_conformation__protein=self.reference_protein,
                                                     protein_segment__slug='ECL2')
                    r_first = list(ref_res)[0].sequence_number
                    r_last = list(ref_res)[-1].sequence_number
                    r_x50 = ref_res.get(generic_number__label='45x50').sequence_number
                except:
                    pass
            if (self.loop_label=='ECL2' and 'ECL2_1' not in self.loop_template_structures) or self.loop_label!='ECL2':
                for template in self.loop_template_structures:
                    output = OrderedDict()
                    try:
                        if template==self.main_structure or template=='aligned':
                            if template=='aligned':
                                self.aligned = True
                            else:
                                self.aligned = False
                            try:
                                loop_res = [r.sequence_number for r in list(Residue.objects.filter(
                                                                            protein_conformation=self.main_structure.protein_conformation,
                                                                            protein_segment__slug=self.loop_label))]
                                inter_array = parse.fetch_residues_from_pdb(self.main_structure,loop_res)
                                self.loop_output_structure = self.main_structure
                                for id_, atoms in inter_array.items():
                                    output[str(id_)] = atoms
                                return output
                            except:
                                continue
                        else:
                            b_num = Residue.objects.get(protein_conformation=template.protein_conformation,
                                                        generic_number__label=last_before_gn).sequence_number
                            a_num = Residue.objects.get(protein_conformation=template.protein_conformation,
                                                        generic_number__label=first_after_gn).sequence_number
                            before4 = Residue.objects.filter(protein_conformation=template.protein_conformation, 
                                                             sequence_number__in=[b_num,b_num-1,b_num-2,b_num-3])
                            after4 = Residue.objects.filter(protein_conformation=template.protein_conformation, 
                                                             sequence_number__in=[a_num,a_num+1,a_num+2,a_num+3])
                            loop_residues = Residue.objects.filter(protein_conformation=template.protein_conformation,
                                                                   sequence_number__in=list(range(b_num+1,a_num)))
                            before_gns = [x.sequence_number for x in before4]
                            mid_nums = [x.sequence_number for x in loop_residues]
                            after_gns = [x.sequence_number for x in after4]
                            alt_residues = parse.fetch_residues_from_pdb(template, before_gns+mid_nums+after_gns)
                            orig_residues = parse.fetch_residues_from_pdb(self.main_structure, 
                                                                          orig_before_gns+orig_after_gns)
                            superpose = sp.LoopSuperpose(orig_residues, alt_residues)
                            new_residues = superpose.run()
                            key_list = list(new_residues.keys())[4:-4]
                            for key in key_list:
                                output[key] = new_residues[key]
                            self.loop_output_structure = template
                            return output
                    except:
                        continue
            else:
                output,ECL2_1,ECL2_mid,ECL2_2 = OrderedDict(),OrderedDict(),OrderedDict(),OrderedDict()
                no_first_temp, no_second_temp = True,True
                main_temp_seq = Residue.objects.filter(protein_conformation=self.main_structure.protein_conformation,
                                                       protein_segment__slug=self.loop_label)
                for mid_template in self.loop_template_structures['ECL2_mid']:
                    if mid_template==self.main_structure:
                        ECL2_mid = parse.fetch_residues_from_pdb(self.main_structure,['45x50','45x51','45x52'])
                        x50 = main_temp_seq.get(generic_number__label='45x50').sequence_number
                        break
                orig_residues1 = parse.fetch_residues_from_pdb(self.main_structure,orig_before_gns+['45x50','45x51','45x52'])

                if self.loop_template_structures['ECL2_1']==None:
                    no_first_temp=True
                else:
                    for first_temp in self.loop_template_structures['ECL2_1']:
                        if first_temp==self.main_structure:
                            ECL2_1 = parse.fetch_residues_from_pdb(self.main_structure,list(range(list(main_temp_seq)[0].sequence_number,x50)))
                            no_first_temp=False
                            break
                        else:
                            try:
                                b_num = Residue.objects.get(protein_conformation=first_temp.protein_conformation,
                                                            generic_number__label=last_before_gn).sequence_number
                                before4 = Residue.objects.filter(protein_conformation=first_temp.protein_conformation, 
                                                                 sequence_number__in=[b_num,b_num-1,b_num-2,b_num-3])
                                alt_mid1 = Residue.objects.filter(protein_conformation=first_temp.protein_conformation,
                                                                  protein_segment__slug=self.loop_label, 
                                                                  generic_number__label__in=['45x50','45x51','45x52'])
                                alt1_x50 = alt_mid1.get(generic_number__label='45x50').sequence_number
                                loop_res1 = Residue.objects.filter(protein_conformation=first_temp.protein_conformation,
                                                                   protein_segment__slug=self.loop_label,
                                                                   sequence_number__in=list(range(b_num, alt1_x50)))
                                before_gns = [x.sequence_number for x in before4]
                                mid_gns1 = [x.sequence_number for x in loop_res1]
                                alt_residues1 = parse.fetch_residues_from_pdb(first_temp,before_gns+mid_gns1+['45x50','45x51','45x52'])
                                superpose = sp.LoopSuperpose(orig_residues1,alt_residues1,ECL2=True,part=1)
                                new_residues = superpose.run()
                                key_list = list(new_residues.keys())[4:-3]
                                for key in key_list:
                                    ECL2_1["1_"+key] = new_residues[key]
                                no_first_temp=False
                                break
                            except:
                                no_first_temp=True

                if no_first_temp==True:
                    for i in range(1,r_x50-r_first+1):
                        ECL2_1['1_'+str(i)]='x'
                        first_temp=None
                orig_residues2 = parse.fetch_residues_from_pdb(self.main_structure,['45x50','45x51','45x52']+orig_after_gns)
                if self.loop_template_structures['ECL2_2']==None:
                    no_second_temp=True
                else:
                    for second_temp in self.loop_template_structures['ECL2_2']:
                        if second_temp==self.main_structure:
                            ECL2_2 = parse.fetch_residues_from_pdb(self.main_structure,list(range(x50+3,list(main_temp_seq)[-1].sequence_number+1)))
                            no_second_temp=False
                            break
                        else:
                            try:
                                a_num = Residue.objects.get(protein_conformation=second_temp.protein_conformation,
                                                            generic_number__label=first_after_gn).sequence_number
                                after4 = Residue.objects.filter(protein_conformation=first_temp.protein_conformation, 
                                                                sequence_number__in=[a_num,a_num+1,a_num+2,a_num+3])
                                alt_mid2 = Residue.objects.filter(protein_conformation=second_temp.protein_conformation,
                                                                  protein_segment__slug=self.loop_label, 
                                                                  generic_number__label__in=['45x50','45x51','45x52'])
                                alt2_x50 = alt_mid2.get(generic_number__label='45x50').sequence_number
                                loop_res2 = Residue.objects.filter(protein_conformation=second_temp.protein_conformation,
                                                                   protein_segment__slug=self.loop_label,
                                                                   sequence_number__in=list(range(alt2_x50+3, a_num)))
                                mid_gns2 = [x.sequence_number for x in loop_res2]
                                after_gns = [x.sequence_number for x in after4]
                                alt_residues2 = parse.fetch_residues_from_pdb(second_temp,['45x50','45x51','45x52']+mid_gns2+after_gns)
                                superpose = sp.LoopSuperpose(orig_residues2,alt_residues2,ECL2=True,part=2)
                                new_residues = superpose.run()
                                key_list = list(new_residues.keys())[3:-4]
                                for key in key_list:
                                    ECL2_2["2_"+key] = new_residues[key]
                                no_second_temp=False
                                break
                            except:
                                no_second_temp=True

                if no_second_temp==True:
                    for j in range(1,r_last-r_x50-1):
                        ECL2_2['2_'+str(j)]='x'
                        second_temp=None
                output['ECL2_1'] = ECL2_1
                output['ECL2_mid'] = ECL2_mid
                output['ECL2_2'] = ECL2_2
                self.loop_output_structure = [first_temp,mid_template,second_temp]
                return output
            if len(output.keys())==0:
                return None
        else:
            return None
                    
    def insert_loop_to_arrays(self, loop_output_structure, main_pdb_array, loop_template, reference_dict, 
                              template_dict, alignment_dict):
        ''' Updates the homology model with loop segments. Inserts previously fetched lists of loop Atom objects to 
            the proper arrays, dictionaries.
            
            @param loop_output_structure: Structure object of loop template.
            @param main_pdb_array: nested OrderedDict(), output of GPCRDBParsingPDB().pdb_array_creator().
            @param loop_template: OrderedDict() of loop template with lists of Atom objects as values.
            @param reference_dict: reference dictionary of AlignedReferenceTemplate.
            @param template_dict: template dictionary of AlignedReferenceTemplate.
            @param alignment_dict: alignment dictionary of AlignedReferenceTemplate.
        '''
        shorter_ref, shorter_temp = False, False
        try:
            for r,t in zip(reference_dict[self.loop_label],template_dict[self.loop_label]):
                if reference_dict[self.loop_label][r]=='-':
                    shorter_ref = True
                elif template_dict[self.loop_label][t]=='-':
                    shorter_temp = True
        except:
            pass
        if loop_template!=None and loop_output_structure!=self.main_structure:
            loop_keys = list(loop_template.keys())[1:-1]
            continuous_loop = False
            self.main_pdb_array = self.discont_loop_insert_to_pdb(main_pdb_array, loop_template, loop_output_structure)           
        elif loop_template!=None and loop_output_structure==self.main_structure or self.aligned==True and (shorter_ref==True or shorter_temp==True):
            loop_keys = list(loop_template.keys())
            continuous_loop = True
            temporary_dict = OrderedDict()
            try:
                if len(loop_keys)<len(template_dict[self.loop_label]):
                    counter=0
                    for i in template_dict[self.loop_label]:
                        if i.replace('x','.') in loop_keys:
                            temporary_dict[i.replace('x','.')] = loop_template[i.replace('x','.')]
                        else:
                            temporary_dict['gap{}'.format(str(counter))] = '-'
                        counter+=1
                    loop_template = temporary_dict
            except:
                pass
            self.main_pdb_array = self.cont_loop_insert_to_pdb(main_pdb_array, loop_template)
        else:
            self.main_pdb_array = main_pdb_array
        
        if loop_template!=None:
            temp_ref_dict, temp_temp_dict, temp_aligned_dict = OrderedDict(),OrderedDict(),OrderedDict()
            if continuous_loop==True:
                if shorter_ref==True and shorter_temp==False:
                    ref_residues = list(reference_dict[self.loop_label].values())
                elif shorter_ref==True and shorter_temp==True:
                    ref_residues = list(reference_dict[self.loop_label].values())
                elif shorter_ref==False and shorter_temp==True:
                    ref_residues = list(reference_dict[self.loop_label].values())
                else:
                    ref_residues = [x.amino_acid for x in Residue.objects.filter(protein_conformation__protein=self.reference_protein,
                                                           protein_segment__slug=self.loop_label)]
            else:
                ref_residues = list(Residue.objects.filter(protein_conformation__protein=self.reference_protein,
                                                           protein_segment__slug=self.loop_label))
            for ref_seg, temp_seg, aligned_seg in zip(reference_dict, template_dict, alignment_dict):
                if ref_seg[0]=='T' and self.segment_order[self.loop_label]-self.segment_order[ref_seg[:4]]==0.5:
                    temp_ref_dict[ref_seg] = reference_dict[ref_seg]
                    temp_temp_dict[temp_seg] = template_dict[temp_seg]
                    temp_aligned_dict[aligned_seg] = alignment_dict[aligned_seg]
                    input_residues = list(loop_template.keys())
                    ref_loop_seg, temp_loop_seg, aligned_loop_seg = OrderedDict(),OrderedDict(),OrderedDict()
                    if continuous_loop==True:
                        l_res=0
                        for r_res, r_id in zip(ref_residues, input_residues):
                            l_res+=1
                            try:
                                loop_gn = Residue.objects.get(protein_conformation=self.main_structure.protein_conformation, 
                                                              generic_number__label=r_id.replace('.','x')).generic_number.label
                            except:
                                try:
                                    Residue.objects.get(protein_conformation=self.main_structure.protein_conformation, 
                                                        sequence_number=r_id)
        #### Possible bug
                                    loop_gn = self.loop_label+'|'+str(l_res)
                                except:
                                    loop_gn = self.loop_label+'?'+str(l_res)
                            ref_loop_seg[loop_gn] = r_res
                            try:
                                temp_loop_seg[loop_gn] = PDB.Polypeptide.three_to_one(loop_template[r_id][0].get_parent().get_resname())
                            except:
                                temp_loop_seg[loop_gn] = '-'
                            if ref_loop_seg[loop_gn]==temp_loop_seg[loop_gn]:                        
                                aligned_loop_seg[loop_gn] = ref_loop_seg[loop_gn]
                            elif ref_loop_seg[loop_gn]=='-' or temp_loop_seg[loop_gn]=='-':
                                aligned_loop_seg[loop_gn] = '-'    
                            else:
                                aligned_loop_seg[loop_gn] = '.'    
                        self.new_label = self.loop_label+'_cont'
                        temp_ref_dict[self.loop_label+'_cont'] = ref_loop_seg
                        temp_temp_dict[self.loop_label+'_cont'] = temp_loop_seg
                        temp_aligned_dict[self.loop_label+'_cont'] = aligned_loop_seg
                    else:
                        l_res=1
                        ref_loop_seg[self.loop_label+'?'+'1'] = ref_residues[0].amino_acid
                        temp_loop_seg[self.loop_label+'?'+'1'] = 'x'
                        aligned_loop_seg[self.loop_label+'?'+'1'] = 'x'
                        for r_res, r_id in zip(ref_residues[1:-1], input_residues[1:-1]):
                            l_res+=1
                            try:
                                loop_gn = Residue.objects.get(protein_conformation=loop_output_structure.protein_conformation, 
                                                              sequence_number=r_id).generic_number.label
                            except:
                                loop_gn = self.loop_label+'|'+str(l_res)
                            ref_loop_seg[loop_gn] = r_res.amino_acid
                            temp_loop_seg[loop_gn] = PDB.Polypeptide.three_to_one(loop_template[r_id][0].get_parent().get_resname())
                            if ref_loop_seg[loop_gn]==temp_loop_seg[loop_gn]:                        
                                aligned_loop_seg[loop_gn] = ref_loop_seg[loop_gn]
                            else:
                                aligned_loop_seg[loop_gn] = '.'
                        ref_loop_seg[self.loop_label+'?'+str(l_res+1)] = ref_residues[-1].amino_acid
                        temp_loop_seg[self.loop_label+'?'+str(l_res+1)] = 'x'
                        aligned_loop_seg[self.loop_label+'?'+str(l_res+1)] = 'x'
                        self.new_label = self.loop_label+'_dis'
                        temp_ref_dict[self.loop_label+'_dis'] = ref_loop_seg
                        temp_temp_dict[self.loop_label+'_dis'] = temp_loop_seg
                        temp_aligned_dict[self.loop_label+'_dis'] = aligned_loop_seg
                else:
                    temp_ref_dict[ref_seg] = reference_dict[ref_seg]
                    temp_temp_dict[temp_seg] = template_dict[temp_seg]
                    temp_aligned_dict[aligned_seg] = alignment_dict[aligned_seg]
            self.reference_dict = temp_ref_dict
            self.template_dict = temp_temp_dict
            self.alignment_dict = temp_aligned_dict
            try:
                del self.reference_dict[self.loop_label]
                del self.template_dict[self.loop_label]
                del self.alignment_dict[self.loop_label]
            except:
                pass
        else:
            self.reference_dict = reference_dict
            self.template_dict = template_dict
            self.alignment_dict = alignment_dict
            try:
                del self.reference_dict[self.loop_label]
                del self.template_dict[self.loop_label]
                del self.alignment_dict[self.loop_label]
            except:
                pass
        return self
    
    def insert_ECL2_to_arrays(self, loop_output_structure, main_pdb_array, loop_template, reference_dict, 
                              template_dict, alignment_dict):
        temp_array = OrderedDict()
        # first part
        if loop_output_structure[0]!=None:
            if loop_output_structure[0]==self.main_structure:
                temp_array = self.cont_loop_insert_to_pdb(main_pdb_array, loop_template['ECL2_1'], ECL2='')
            else:
                temp_array = self.discont_loop_insert_to_pdb(main_pdb_array, loop_template['ECL2_1'], 
                                                             loop_output_structure, ECL2='')
        else:
            temp_array = self.gap_ECL2(main_pdb_array,loop_template['ECL2_1'])
        # middle part
        for key, res in loop_template['ECL2_mid'].items():
            temp_array['ECL2'][key] = res
        # second part
        l_res = len(temp_array['ECL2'])
        if loop_output_structure[2]!=None:
            if loop_output_structure[2]==self.main_structure:
                for key, res in loop_template['ECL2_2'].items():
                    l_res+=1
                    if '.' in key:
                        temp_array['ECL2'][key] = res
                    else:
                        temp_array['ECL2'][self.loop_label+'|'+str(l_res)] = res
            else:
                loop_keys = list(loop_template['ECL2_2'].keys())[1:-1]
                temp_array['ECL2'][self.loop_label+'?'+str(l_res+1)] = 'x'
                for key in loop_keys:
                    l_res+=1
                    temp_array['ECL2'][self.loop_label+'|'+str(l_res)] = loop_template['ECL2_2'][key]
                temp_array['ECL2'][self.loop_label+'?'+str(l_res+1)] = 'x'
        else:
            for key, res in loop_template['ECL2_2'].items():
                l_res+=1
                temp_array['ECL2'][self.loop_label+'?'+str(l_res)] = '-'
        self.main_pdb_array = temp_array
        temp_ref_dict, temp_temp_dict, temp_aligned_dict = OrderedDict(),OrderedDict(),OrderedDict()
        ref_residues = list(Residue.objects.filter(protein_conformation__protein=self.reference_protein, 
                                                   protein_segment__slug='ECL2'))
        for ref_seg, temp_seg, aligned_seg in zip(reference_dict, template_dict, alignment_dict):
            if ref_seg[0]=='T' and self.segment_order[self.loop_label]-self.segment_order[ref_seg[:4]]==0.5:
                temp_ref_dict[ref_seg] = reference_dict[ref_seg]
                temp_temp_dict[temp_seg] = template_dict[temp_seg]
                temp_aligned_dict[aligned_seg] = alignment_dict[aligned_seg]
                temp_ref_dict['ECL2'],temp_temp_dict['ECL2'],temp_aligned_dict['ECL2'] = OrderedDict(),OrderedDict(),OrderedDict()
                for ref, key in zip(ref_residues, self.main_pdb_array['ECL2']):
                    temp_ref_dict['ECL2'][key] = ref.amino_acid
                    try:
                        temp_temp_dict['ECL2'][key] = PDB.Polypeptide.three_to_one(
                                                        self.main_pdb_array['ECL2'][key][0].get_parent().get_resname())
                    except:
                        temp_temp_dict['ECL2'][key] = self.main_pdb_array['ECL2'][key]
                    if temp_ref_dict['ECL2'][key]==temp_temp_dict['ECL2'][key]:
                        temp_aligned_dict['ECL2'][key] = temp_ref_dict['ECL2'][key]
                    elif temp_temp_dict['ECL2'][key]=='x':
                        temp_aligned_dict['ECL2'][key] = 'x'
                    elif temp_temp_dict['ECL2'][key]=='-':
                        temp_aligned_dict['ECL2'][key] = '-'
                    else:
                        temp_aligned_dict['ECL2'][key] = '.'
            else:
                temp_ref_dict[ref_seg] = reference_dict[ref_seg]
                temp_temp_dict[temp_seg] = template_dict[temp_seg]
                temp_aligned_dict[aligned_seg] = alignment_dict[aligned_seg]
        self.reference_dict = temp_ref_dict
        self.template_dict = temp_temp_dict
        self.alignment_dict = temp_aligned_dict       
        return self       
        
    def gap_ECL2(self, main_pdb_array, loop_template):
        temp_array, temp_loop = OrderedDict(), OrderedDict()
        for seg_label, gns in main_pdb_array.items():
            if self.segment_order[self.loop_label]-self.segment_order[seg_label[:4]]==0.5:
                temp_array[seg_label] = gns
                l_res = 0
                for key in loop_template:
                    l_res+=1
                    temp_loop[self.loop_label+'?'+str(l_res)] = '-'
                temp_array[self.loop_label] = temp_loop
            else:
                temp_array[seg_label] = gns
        return temp_array
                
    def cont_loop_insert_to_pdb(self, main_pdb_array, loop_template, ECL2=None):
        temp_array, temp_loop = OrderedDict(), OrderedDict()
        for seg_label, gns in main_pdb_array.items():
            if self.segment_order[self.loop_label]-self.segment_order[seg_label[:4]]==0.5:
                temp_array[seg_label] = gns
                l_res = 0
                for key in loop_template:
                    l_res+=1
                    if '.' in key:
                        temp_loop[key] = loop_template[key]
                    elif 'gap' in key:
                        temp_loop[self.loop_label+'?'+str(l_res)] = loop_template[key]
                    else:
                        temp_loop[self.loop_label+'|'+str(l_res)] = loop_template[key]   
                if ECL2!=None:
                    temp_array[self.loop_label] = temp_loop
                else:                             
                    temp_array[self.loop_label+'_cont'] = temp_loop
            else:
                temp_array[seg_label] = gns
        return temp_array
        
    def discont_loop_insert_to_pdb(self, main_pdb_array, loop_template, loop_output_structure, ECL2=None):
        temp_array, temp_loop = OrderedDict(), OrderedDict()
        loop_keys = list(loop_template.keys())[1:-1]
        for seg_label, gns in main_pdb_array.items():
            if self.segment_order[self.loop_label]-self.segment_order[seg_label[:4]]==0.5:
                temp_array[seg_label] = gns
                l_res = 1
                temp_loop[self.loop_label+'?'+'1'] = 'x'
                for key in loop_keys:
                    l_res+=1
                    try:
                        loop_gn = Residue.objects.get(protein_conformation=loop_output_structure.protein_conformation, 
                                                      sequence_number=key).generic_number.label.replace('x','.')
                        temp_loop[loop_gn] = loop_template[key]
                    except:
                        temp_loop[self.loop_label+'|'+str(l_res)] = loop_template[key]
                temp_loop[self.loop_label+'?'+str(l_res+1)] = 'x'
                if ECL2!=None:
                    temp_array[self.loop_label] = temp_loop
                else:                    
                    temp_array[self.loop_label+'_dis'] = temp_loop
            else:
                temp_array[seg_label] = gns
        return temp_array
        
    def insert_gaps_for_loops_to_arrays(self, main_pdb_array, reference_dict, template_dict, alignment_dict):
        ''' When there is no template for a loop region, this function inserts gaps for that region into the main 
            template, fetches the reference residues and inserts these into the arrays. This allows for Modeller to
            freely model these loop regions.
            
            @param main_pdb_array: nested OrderedDict(), output of GPCRDBParsingPDB().pdb_array_creator().
            @param reference_dict: reference dictionary of AlignedReferenceTemplate.
            @param template_dict: template dictionary of AlignedReferenceTemplate.
            @param alignment_dict: alignment dictionary of AlignedReferenceTemplate.
        '''
        residues = Residue.objects.filter(protein_conformation__protein=self.reference_protein, 
                                          protein_segment__slug=self.loop_label)
        temp_pdb_array = OrderedDict()
        for seg_id, seg in main_pdb_array.items():
            if self.segment_order[self.loop_label]-self.segment_order[seg_id[:4]]==0.5:
                temp_loop = OrderedDict()
                count=0
                temp_pdb_array[seg_id] = seg
                for r in residues:
                    count+=1
                    temp_loop[self.loop_label+'?'+str(count)] = '-'
                temp_pdb_array[self.loop_label+'_free'] = temp_loop
                self.new_label = self.loop_label+'_free'
            else:
                temp_pdb_array[seg_id] = seg
        self.main_pdb_array = temp_pdb_array
        temp_ref_dict, temp_temp_dict, temp_aligned_dict = OrderedDict(), OrderedDict(), OrderedDict()
        for ref_seg, temp_seg, aligned_seg in zip(reference_dict, template_dict, alignment_dict):
            if self.segment_order[self.loop_label]-self.segment_order[ref_seg[:4]]==0.5:
                temp_ref_loop, temp_temp_loop, temp_aligned_loop = OrderedDict(), OrderedDict(), OrderedDict()
                temp_ref_dict[ref_seg] = reference_dict[ref_seg]
                temp_temp_dict[temp_seg] = template_dict[temp_seg]
                temp_aligned_dict[aligned_seg] = alignment_dict[aligned_seg]
                count=0
                for r in residues:
                    count+=1
                    temp_ref_loop[self.loop_label+'?'+str(count)] = r.amino_acid
                    temp_temp_loop[self.loop_label+'?'+str(count)] = '-'
                    temp_aligned_loop[self.loop_label+'?'+str(count)] = '.'
                temp_ref_dict[self.loop_label+'_free'] = temp_ref_loop
                temp_temp_dict[self.loop_label+'_free'] = temp_temp_loop
                temp_aligned_dict[self.loop_label+'_free'] = temp_aligned_loop
            else:
                temp_ref_dict[ref_seg] = reference_dict[ref_seg]
                temp_temp_dict[temp_seg] = template_dict[temp_seg]
                temp_aligned_dict[aligned_seg] = alignment_dict[aligned_seg]
        self.reference_dict = temp_ref_dict
        self.template_dict = temp_temp_dict
        self.alignment_dict = temp_aligned_dict


class Bulges(object):
    ''' Class to handle bulges in GPCR structures.
    '''
    def __init__(self, gn):
        self.gn = gn
        self.bulge_templates = []
        self.template = None
    
    def find_bulge_template(self, similarity_table, bulge_in_reference):
        ''' Searches for bulge template, returns residues of template (5 residues if the bulge is in the reference, 4
            residues if the bulge is in the template). 
            
            @param gn: str, Generic number of bulge, e.g. 1x411 \n
            @param similarity_table: OrderedDict(), table of structures ordered by preference.
            Output of HomologyModeling().create_similarity_table(). \n
            @param bulge_in_reference: boolean, Set it to True if the bulge is in the reference, set it to False if the
            bulge is in the template.
        '''
        gn = self.gn
        parse = GPCRDBParsingPDB()
        for structure, value in similarity_table.items():
            this_anomaly = ProteinAnomaly.objects.filter(generic_number__label=gn)
            anomaly_list = structure.protein_anomalies.all().prefetch_related()
            if bulge_in_reference==True:
                try:
                    for anomaly in this_anomaly:
                        if anomaly in anomaly_list:
                            gn_list = [parse.gn_indecer(gn,'x',-2),parse.gn_indecer(gn,'x',-1),gn,
                                       parse.gn_indecer(gn,'x',+1),parse.gn_indecer(gn,'x',+2)]
                            alt_bulge = parse.fetch_residues_from_pdb(structure, gn_list)
                            self.template = structure
                            return alt_bulge
                except:
                    pass
            elif bulge_in_reference==False:
                try:
                    suitable_temp = []
                    for anomaly in this_anomaly:
                        if anomaly not in anomaly_list:
                            pass
                        else:
                            suitable_temp.append('no')
                    if 'no' not in suitable_temp:
                        gn_list = [parse.gn_indecer(gn,'x',-2), parse.gn_indecer(gn,'x',-1),
                                   parse.gn_indecer(gn,'x',+1), parse.gn_indecer(gn,'x',+2)]
                        alt_bulge = parse.fetch_residues_from_pdb(structure, gn_list)
                        self.template = structure
                        return alt_bulge
                except:
                    pass
        return None
            
            
class Constrictions(object):
    ''' Class to handle constrictions in GPCRs.
    '''
    def __init__(self, gn):
        self.gn = gn
        self.constriction_templates = []
        self.template = None
    
    def find_constriction_template(self, similarity_table, constriction_in_reference):
        ''' Searches for constriction template, returns residues of template (4 residues if the constriction is in the 
            reference, 5 residues if the constriction is in the template). 
            
            @param gn: str, Generic number of constriction, e.g. 7x44 \n
            @param similarity_table: OrderedDict(), table of structures ordered by preference.
            Output of HomologyModeling().create_similarity_table(). \n
            @param constriction_in_reference: boolean, Set it to True if the constriction is in the reference, set it 
            to False if the constriction is in the template.
        '''
        gn = self.gn
        parse = GPCRDBParsingPDB()
        for structure, value in similarity_table.items():
            this_anomaly = ProteinAnomaly.objects.filter(generic_number__label=gn)
            anomaly_list = structure.protein_anomalies.all().prefetch_related()
            if constriction_in_reference==True:
                try:
                    for anomaly in this_anomaly:
                        if anomaly in anomaly_list:
                            gn_list = [parse.gn_indecer(gn,'x',-2),parse.gn_indecer(gn,'x',-1),
                                       parse.gn_indecer(gn,'x',+1),parse.gn_indecer(gn,'x',+2)]
                            alt_const = parse.fetch_residues_from_pdb(structure, gn_list)
                            self.template = structure
                            return alt_const
                except:
                    pass
            elif constriction_in_reference==False:
                try:
                    suitable_temp = []
                    for anomaly in this_anomaly:
                        if anomaly not in anomaly_list:
                            pass
                        else:
                            suitable_temp.append('no')
                    if 'no' not in suitable_temp:
                        gn_list = [parse.gn_indecer(gn,'x',-2), parse.gn_indecer(gn,'x',-1),gn,
                                   parse.gn_indecer(gn,'x',+1), parse.gn_indecer(gn,'x',+2)]
                        alt_const = parse.fetch_residues_from_pdb(structure, gn_list)
                        self.template = structure
                        return alt_const
                except:
                    pass              
        return None
        
        
class GPCRDBParsingPDB(object):
    ''' Class to manipulate cleaned pdb files of GPCRs.
    '''
    def __init__(self):
        self.segment_coding = OrderedDict([(1,'TM1'),(2,'TM2'),(3,'TM3'),(4,'TM4'),(5,'TM5'),(6,'TM6'),(7,'TM7'),(8,'H8')])
    
    def gn_num_extract(self, gn, delimiter):
        ''' Extract TM number and position for formatting.
        
            @param gn: str, Generic number \n
            @param delimiter: str, character between TM and position (usually 'x')
        '''
        try:
            split = gn.split(delimiter)
            return int(split[0]), int(split[1])
        except:
            return '/', '/'
            
    def gn_comparer(self, gn1, gn2, protein_conformation):
        '''
        '''
        res1 = Residue.objects.get(protein_conformation=protein_conformation, generic_number__label=gn1)
        res2 = Residue.objects.get(protein_conformation=protein_conformation, generic_number__label=gn2)
        return res1.sequence_number-res2.sequence_number
            
    def gn_indecer(self, gn, delimiter, direction):
        ''' Get an upstream or downstream generic number from reference generic number.
        
            @param gn: str, Generic number \n
            @param delimiter: str, character between TM and position (usually 'x') \n 
            @param direction: int, n'th position from gn (+ or -)
        '''
        split = self.gn_num_extract(gn, delimiter)
        if split[0]!='/':
            if len(str(split[1]))==2:
                return str(split[0])+delimiter+str(split[1]+direction)
            elif len(str(split[1]))==3:
                if direction<0:
                    direction += 1
                return str(split[0])+delimiter+str(int(str(split[1])[:2])+direction)
        return '/'

    def fetch_residues_from_pdb(self, structure, generic_numbers, modify_bulges=False):
        ''' Fetches specific lines from pdb file by generic number (if generic number is
            not available then by residue number). Returns nested OrderedDict()
            with generic numbers as keys in the outer dictionary, and atom names as keys
            in the inner dictionary.
            
            @param structure: Structure, Structure object where residues should be fetched from \n
            @param generic_numbers: list, list of generic numbers to be fetched \n
            @param modify_bulges: boolean, set it to true when used for bulge switching. E.g. you want a 5x461
            residue to be considered a 5x46 residue. 
        '''
        output = OrderedDict()
        atoms_list = []
        for gn in generic_numbers:
            rotamer=None
            if 'x' in str(gn):      
                rotamer = list(Rotamer.objects.filter(structure__protein_conformation=structure.protein_conformation, 
                        residue__generic_number__label=gn, structure__preferred_chain=structure.preferred_chain))
            else:
                rotamer = list(Rotamer.objects.filter(structure__protein_conformation=structure.protein_conformation, 
                        residue__sequence_number=gn, structure__preferred_chain=structure.preferred_chain))
                try:
                    gn = Residue.objects.get(protein_conformation=structure.protein_conformation,sequence_number=gn).generic_number.label
                except:
                    pass
            if len(rotamer)>1:
                for i in rotamer:
                    if i.pdbdata.pdb.startswith('COMPND')==False:
                        rotamer = i
                        break
            else:
                rotamer = rotamer[0]
            io = StringIO(rotamer.pdbdata.pdb)
            rota_struct = PDB.PDBParser().get_structure('structure', io)[0]
            for chain in rota_struct:
                for residue in chain:
                    for atom in residue:
                        atoms_list.append(atom)
                    if modify_bulges==True and len(gn)==5:
                        output[gn.replace('x','.')[:-1]] = atoms_list
                    else:
                        try:
                            output[gn.replace('x','.')] = atoms_list
                        except:
                            output[str(gn)] = atoms_list
                    atoms_list = []
        return output

    def pdb_array_creator(self, structure=None, filename=None):
        ''' Creates an OrderedDict() from the pdb of a Structure object where residue numbers/generic numbers are 
            keys for the residues, and atom names are keys for the Bio.PDB.Residue objects.
            
            @param structure: Structure, Structure object of protein. When using structure, leave filename=None. \n
            @param filename: str, filename of pdb to be parsed. When using filename, leave structure=None).
        '''
        if structure!=None and filename==None:
            io = StringIO(structure.pdb_data.pdb)
        else:
            io = filename
        residue_array = OrderedDict()
        pdb_struct = PDB.PDBParser(PERMISSIVE=True).get_structure('structure', io)[0]

        assign_gn = as_gn.GenericNumbering(structure=pdb_struct)
        pdb_struct = assign_gn.assign_generic_numbers()
        
        pref_chain = structure.preferred_chain
        for residue in pdb_struct[pref_chain]:
            try:
                if -9.1 < residue['CA'].get_bfactor() < 9.1:
                    gn = str(residue['CA'].get_bfactor())
                    if gn[0]=='-':
                        gn = gn[1:]+'1'
                    elif len(gn.split('.')[1])==1:
                        gn = gn+'0'
                    residue_array[gn] = residue.get_list()
                else:
                    residue_array[str(residue.get_id()[1])] = residue.get_list()
            except:
                logging.warning("Unable to parse {} in {}".format(residue, structure))
        output = OrderedDict()
        for num, label in self.segment_coding.items():
            output[label] = OrderedDict()
        counter=0
        for gn, res in residue_array.items():
            if '.' in gn:
                seg_label = self.segment_coding[int(gn.split('.')[0])]
                output[seg_label][gn] = res
            else:
                try:
                    found_res = Residue.objects.get(protein_conformation=structure.protein_conformation,
                                                    sequence_number=gn)
                    found_gn = str(found_res.generic_number.label).replace('x','.')
                    if -9.1 < float(found_gn) < 9.1:
                        seg_label = self.segment_coding[int(found_gn.split('.')[0])]
                        output[seg_label][found_gn] = res
                except:
                    pass
            counter+=1
        return output
   
   
class CreateStatistics(object):
    ''' Statistics dictionary for HomologyModeling.
    '''
    def __init__(self, reference):
        self.reference = reference
        self.info_dict = OrderedDict()
    
    def __repr__(self):
        return "<{} \n {} \n>".format(self.reference, self.info_dict)
        
    def items(self):
        ''' Returns the OrderedDict().items().
        '''
        return self.info_dict.items()
    
    def add_info(self, info_name, info):
        ''' Adds new information to the statistics dictionary.
        
            @param info_name: str, info name as dictionary key
            @param info: object, any object as value
        '''
        self.info_dict[info_name] = info

