# -*- coding: utf-8 -*-
# Generated by Django 1.9.1 on 2016-07-06 15:27
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('construct', '0002_auto_20160706_1605'),
    ]

    operations = [
        migrations.AlterField(
            model_name='crystallizationligandconc',
            name='ligand_conc',
            field=models.FloatField(null=True),
        ),
    ]