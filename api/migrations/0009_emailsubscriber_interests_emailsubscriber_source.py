from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0008_naventry_company_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailsubscriber",
            name="source",
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="emailsubscriber",
            name="interests",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
