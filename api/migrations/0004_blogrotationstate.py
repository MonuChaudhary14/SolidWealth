from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0003_blogpost"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlogRotationState",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "singleton_key",
                    models.CharField(default="featured", max_length=32, unique=True),
                ),
                ("ordered_blog_ids", models.JSONField(blank=True, default=list)),
                ("cursor", models.PositiveIntegerField(default=0)),
                ("cycle_started_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
