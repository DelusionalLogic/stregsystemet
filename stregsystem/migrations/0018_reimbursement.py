# Generated by Django 2.2.28 on 2024-04-14 13:32

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('stregsystem', '0017_auto_20220511_1738'),
    ]

    operations = [
        migrations.CreateModel(
            name='Reimbursement',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.IntegerField()),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='stregsystem.Member')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='stregsystem.Product')),
            ],
        ),
    ]
