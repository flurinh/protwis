﻿from common.diagrams_arrestin import DrawArrestinPlot
from common.diagrams_gpcr import DrawHelixBox, DrawSnakePlot
from common.diagrams_gprotein import DrawGproteinPlot
from django.db import models
from residue.models import (Residue, ResidueDataPoint, ResidueDataType,
                            ResidueGenericNumberEquivalent,
                            ResidueNumberingScheme)


class Protein(models.Model):
    parent = models.ForeignKey('self', null=True, on_delete=models.CASCADE)
    family = models.ForeignKey('ProteinFamily', on_delete=models.CASCADE)
    species = models.ForeignKey('Species', on_delete=models.CASCADE)
    source = models.ForeignKey('ProteinSource', on_delete=models.CASCADE)
    residue_numbering_scheme = models.ForeignKey('residue.ResidueNumberingScheme', on_delete=models.CASCADE, null=True)
    sequence_type = models.ForeignKey('ProteinSequenceType', on_delete=models.CASCADE)
    states = models.ManyToManyField('ProteinState', through='ProteinConformation')
    endogenous_ligands = models.ManyToManyField('ligand.Ligand')
    web_links = models.ManyToManyField('common.WebLink')
    entry_name = models.SlugField(max_length=100, unique=True)
    accession = models.CharField(max_length=100, db_index=True, null=True)
    name = models.CharField(max_length=200)
    sequence = models.TextField()

    def entry_short(self):
        return self.entry_name.split("_")[0].upper()

    def short(self):
        return self.name.replace(" receptor","").replace("-adrenoceptor","")

    def __str__(self):
        if not self.entry_name:
            return self.name
        else:
            return self.entry_name

    class Meta():
        db_table = 'protein'

    def get_protein_class(self):
        tmp = self.family
        while tmp.parent.parent is not None:
            tmp = tmp.parent
        return tmp.name

    def get_helical_box(self):
        residuelist = Residue.objects.filter(protein_conformation__protein__entry_name=str(self)).prefetch_related('protein_segment','display_generic_number','generic_number')
        return DrawHelixBox(residuelist,self.get_protein_class(),str(self))

    def get_snake_plot(self):
        residuelist = Residue.objects.filter(protein_conformation__protein__entry_name=str(self)).prefetch_related('protein_segment','display_generic_number','generic_number')
        return DrawSnakePlot(residuelist,self.get_protein_class(),str(self))

    def get_helical_box_no_buttons(self):
        residuelist = Residue.objects.filter(protein_conformation__protein__entry_name=str(self)).prefetch_related('protein_segment','display_generic_number','generic_number')
        return DrawHelixBox(residuelist,self.get_protein_class(),str(self), nobuttons=1)

    def get_snake_plot_no_buttons(self):
        residuelist = Residue.objects.filter(protein_conformation__protein__entry_name=str(self)).prefetch_related('protein_segment','display_generic_number','generic_number')
        return DrawSnakePlot(residuelist,self.get_protein_class(),str(self), nobuttons=1)

    def get_gprotein_plot(self):
        residuelist = Residue.objects.filter(protein_conformation__protein__entry_name=str(self)).prefetch_related('protein_segment','display_generic_number','generic_number')
        return DrawGproteinPlot(residuelist,self.get_protein_class(),str(self))

    def get_arrestin_plot(self):
        residuelist = Residue.objects.filter(protein_conformation__protein__entry_name=str(self)).prefetch_related('protein_segment','display_generic_number','generic_number')
        return DrawArrestinPlot(residuelist,self.get_protein_class(),str(self))

    def get_protein_family(self):
        tmp = self.family
        while tmp.parent.parent.parent is not None:
            tmp = tmp.parent
        return tmp.name

    def get_protein_subfamily(self):
        tmp = self.family
        while tmp.parent.parent.parent.parent is not None:
            tmp = tmp.parent
        return tmp.name


class ProteinConformation(models.Model):
    protein = models.ForeignKey('Protein', on_delete=models.CASCADE)
    state = models.ForeignKey('ProteinState', on_delete=models.CASCADE)
    protein_anomalies = models.ManyToManyField('protein.ProteinAnomaly')

    # non-database attributes
    identity = 0 # % identity to a reference sequence in an alignment
    similarity = 0 # % similarity to a reference sequence in an alignment (% BLOSUM62 score > 0)
    similarity_score = 0 # similarity score to a reference sequence in an alignment (sum of BLOSUM62 scores)
    alignment = 0 # residues formatted for use in an Alignment class
    alignment_list = 0 # FIXME redundant, remove when dependecies are removed

    def __str__(self):
        return self.protein.entry_name + " (" + self.state.slug + ")"

    def generate_sites(self):
        self.sodium_pocket()

    @property
    def is_sodium(self):
        # Avoid filter, to utilise if site_protein_conformation is prefetched, otherwise it generates a DB call
        for s in self.site_protein_conformation.all():
            if s.site.slug=='sodium_pocket':
                return True
        return False

    def sodium_pocket(self):
        try:
            site = Site.objects.get(slug='sodium_pocket')
        except:
            site = Site.objects.create(slug='sodium_pocket', name='Sodium ion pocket')
        try:
            ex_site = IdentifiedSites.objects.get(protein_conformation=self)

            if len(ex_site.residues.all())==2 and ex_site.site==site:
                return
            else:
                raise Exception
        except:
            resis = Residue.objects.filter(protein_conformation=self, display_generic_number__label__in=[dgn('2x50', self),
                                                                                                         dgn('3x39', self)])
            parent_resis = Residue.objects.filter(protein_conformation__protein=self.protein.parent, display_generic_number__label__in=[dgn('2x50', self),
                                                                                                                                        dgn('3x39', self)])
            if len(resis)==2:
                if resis[0].amino_acid in ['D','E'] and resis[1].amino_acid in ['S','T']:
                    istate, created = IdentifiedSites.objects.get_or_create(protein_conformation=self, site=site)
                    if created:
                        istate.residues.add(resis[0], resis[1])

    class Meta():
        ordering = ('id', )
        db_table = "protein_conformation"


class IdentifiedSites(models.Model):
    protein_conformation = models.ForeignKey('protein.ProteinConformation', related_name='site_protein_conformation', on_delete=models.CASCADE)
    site = models.ForeignKey('Site', on_delete=models.CASCADE)
    residues = models.ManyToManyField('residue.Residue', related_name='site_residue')


class Site(models.Model):
    slug = models.CharField(max_length=20)
    name = models.CharField(max_length=30)


class ProteinState(models.Model):
    slug = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.slug

    class Meta():
        db_table = "protein_state"


class Gene(models.Model):
    proteins = models.ManyToManyField('Protein', related_name='genes')
    species = models.ForeignKey('Species', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    position = models.SmallIntegerField()

    def __str__(self):
        return self.name

    class Meta():
        ordering = ('position', )
        unique_together = ('name', 'species','position')
        db_table = 'gene'


class Species(models.Model):
    latin_name = models.CharField(max_length=100, unique=True)
    common_name = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.latin_name

    class Meta():
        db_table = 'species'


class ProteinAlias(models.Model):
    protein = models.ForeignKey('Protein', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    position = models.SmallIntegerField()

    def __str__(self):
        return self.name

    class Meta():
        ordering = ('position', )
        db_table = 'protein_alias'


class ProteinSet(models.Model):
    proteins = models.ManyToManyField('Protein')
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

    class Meta():
        db_table = 'protein_set'


class ProteinSegment(models.Model):
    slug = models.SlugField(max_length=100)
    name = models.CharField(max_length=50)
    category = models.CharField(max_length=50)
    fully_aligned = models.BooleanField(default=False)
    partial = models.BooleanField(default=False)
    proteinfamily = models.CharField(max_length=20)

    def __str__(self):
        return self.slug

    class Meta():
        ordering = ('id', )
        db_table = 'protein_segment'
        unique_together = ('slug', 'proteinfamily')


class ProteinSource(models.Model):
    name = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name

    class Meta():
        db_table = 'protein_source'


class ProteinFamily(models.Model):
    parent = models.ForeignKey('self', null=True, on_delete=models.CASCADE)
    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=200)

    def short(self):
        return self.name.replace("Class ","").replace(" receptors","").replace(" receptor family","")

    def shorter(self):
        import re
        return re.sub(r'\(.*\)', ' ', self.name).replace("Class ","").replace(" receptors","").replace(" receptor family","")

    def __str__(self):
        return self.name

    class Meta():
        db_table = 'protein_family'
        ordering = ('id', )


class ProteinSequenceType(models.Model):
    slug = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.slug

    class Meta():
        db_table = 'protein_sequence_type'


class ProteinAnomaly(models.Model):
    anomaly_type = models.ForeignKey('ProteinAnomalyType', on_delete=models.CASCADE)
    generic_number = models.ForeignKey('residue.ResidueGenericNumber', on_delete=models.CASCADE)

    def __str__(self):
        return self.generic_number.label

    class Meta():
        ordering = ('generic_number__label', )
        db_table = 'protein_anomaly'
        unique_together = ('anomaly_type', 'generic_number')


class ProteinAnomalyType(models.Model):
    slug = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.slug

    class Meta():
        db_table = 'protein_anomaly_type'


class ProteinAnomalyRuleSet(models.Model):
    protein_anomaly = models.ForeignKey('ProteinAnomaly', related_name='rulesets', on_delete=models.CASCADE)
    exclusive = models.BooleanField(default=False)

    def __str__(self):
        return self.protein_anomaly.generic_number.label

    class Meta():
        db_table = 'protein_anomaly_rule_set'
        ordering = ('id', )


class ProteinAnomalyRule(models.Model):
    rule_set = models.ForeignKey('ProteinAnomalyRuleSet', related_name='rules', on_delete=models.CASCADE)
    generic_number = models.ForeignKey('residue.ResidueGenericNumber', on_delete=models.CASCADE)
    amino_acid = models.CharField(max_length=1)
    negative = models.BooleanField(default=False)

    def __str__(self):
        return "{} {}".format(self.generic_number.label, self.amino_acid)

    class Meta():
        db_table = 'protein_anomaly_rule'


class ProteinFusion(models.Model):
    proteins = models.ManyToManyField('Protein', through='ProteinFusionProtein')
    name = models.CharField(max_length=100, unique=True)
    sequence = models.TextField(null=True)

    def __str__(self):
        return self.name

    class Meta():
        db_table = 'protein_fusion'


class ProteinFusionProtein(models.Model):
    protein = models.ForeignKey('Protein', on_delete=models.CASCADE)
    protein_fusion = models.ForeignKey('ProteinFusion', on_delete=models.CASCADE)
    segment_before = models.ForeignKey('ProteinSegment', related_name='segment_before', on_delete=models.CASCADE)
    segment_after = models.ForeignKey('ProteinSegment', related_name='segment_after', on_delete=models.CASCADE)

    def __str__(self):
        return self.protein.name + " " + self.protein_fusion.name

    class Meta():
        db_table = 'protein_fusion_protein'


class ProteinConformationTemplateStructure(models.Model):
    protein_conformation = models.ForeignKey('ProteinConformation', on_delete=models.CASCADE)
    protein_segment = models.ForeignKey('ProteinSegment', on_delete=models.CASCADE)
    structure = models.ForeignKey('structure.Structure', on_delete=models.CASCADE)

    def __str__(self):
        return self.protein_conformation.protein.name + " " + self.protein_segment.slug \
               + " " + self.structure.pdb_code.index

    class Meta():
        db_table = 'protein_conformation_template_structure'


class ProteinGProtein(models.Model):
    proteins = models.ManyToManyField('Protein', through='ProteinGProteinPair', through_fields=('g_protein','protein'))
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=20, unique=True)

    def __str__(self):
        return self.name

    class Meta():
        db_table = 'protein_gprotein'


class ProteinGProteinPair(models.Model):
    protein = models.ForeignKey('Protein', on_delete=models.CASCADE)
    g_protein = models.ForeignKey('ProteinGProtein', on_delete=models.CASCADE)
    transduction = models.TextField(null=True)
    source = models.TextField(null=True) # GuideToPharma, Aska, Bouvier
    emax_mean = models.FloatField(null=True, blank=True)
    emax_sem = models.FloatField(null=True, blank=True)
    emax_dnorm = models.FloatField(null=True, blank=True)
    emax_deg = models.FloatField(null=True, blank=True)  # Value from David Gloriam
    pec50_mean = models.FloatField(null=True, blank=True)
    pec50_sem = models.FloatField(null=True, blank=True)
    pec50_dnorm = models.FloatField(null=True, blank=True)
    pec50_deg = models.FloatField(null=True, blank=True)  # Value from David Gloriam
    log_rai_mean = models.FloatField(null=True, blank=True)
    log_rai_sem  = models.FloatField(null=True, blank=True)
    logmaxec50_deg = models.FloatField(null=True, blank=True) # Value from David Gloriam
    g_protein_subunit = models.ForeignKey('Protein', on_delete=models.CASCADE, related_name='gprotein', null=True)
    references = models.ManyToManyField('common.Publication')


    def __str__(self):
        # NOTE: The following return breaks when there's no data for transduction since a null
        # can't be concatenated with strings.
        # return self.protein.entry_name + ", " + self.g_protein.name + ", " + self.transduction
        return "{} {} {}".format(self.protein.entry_name,  self.g_protein.name, self.transduction)

    class Meta():
        db_table = 'protein_gprotein_pair'


class ProteinArrestinPair(models.Model):
    protein = models.ForeignKey('Protein', on_delete=models.CASCADE)
    source = models.TextField(null=True)  # Bouvier
    emax_deg = models.FloatField(null=True, blank=True)  # Value from David Gloriam
    pec50_deg = models.FloatField(null=True, blank=True)  # Value from David Gloriam
    logmaxec50_deg = models.FloatField(null=True, blank=True) # Value from David Gloriam
    arrestin_subtype = models.ForeignKey('Protein', on_delete=models.CASCADE, related_name='arrestin', null=True)
    references = models.ManyToManyField('common.Publication')


    def __str__(self):
        return "{} {}".format(self.protein.entry_name, self.arrestin_subtype)

    class Meta():
        db_table = 'protein_arrestin_pair'

def dgn(gn, protein_conformation):
    """Convert generic number to display generic number."""
    scheme = ResidueNumberingScheme.objects.get(slug=protein_conformation.protein.residue_numbering_scheme.slug)
    convert_gn = ResidueGenericNumberEquivalent.objects.get(label=gn, scheme=scheme).default_generic_number.label
    return Residue.objects.get(protein_conformation=protein_conformation, generic_number__label=convert_gn).display_generic_number.label
