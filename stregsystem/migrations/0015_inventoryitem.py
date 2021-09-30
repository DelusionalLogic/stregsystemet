# Generated by Django 2.2.13 on 2021-09-30 08:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stregsystem', '0014_mobilepayment_nullable_customername_20210908_1522'),
    ]

    operations = [
        migrations.CreateModel(
            name='InventoryItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64)),
                ('price', models.PositiveIntegerField(default=0)),
                ('quantity', models.PositiveIntegerField(default=0)),
                ('parent_item', models.ManyToManyField(blank=True, to='stregsystem.Product')),
            ],
        ),
    ]
