from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_emailsubscriber_mobile_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketSnapshot",
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
                ("snapshot_date", models.DateField(db_index=True, unique=True)),
                (
                    "gold_price",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=20, null=True
                    ),
                ),
                (
                    "silver_price",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=20, null=True
                    ),
                ),
                (
                    "crude_oil_price",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=20, null=True
                    ),
                ),
                (
                    "bitcoin_price",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=20, null=True
                    ),
                ),
                (
                    "nifty_50_value",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=20, null=True
                    ),
                ),
                (
                    "sensex_value",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=20, null=True
                    ),
                ),
                (
                    "usd_inr_rate",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=20, null=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-snapshot_date", "-created_at"],
            },
        ),
    ]
