import re

from django.db import models


class NavEntry(models.Model):
    scheme_code = models.CharField(max_length=64, db_index=True)
    isin = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    scheme_name = models.CharField(max_length=512, db_index=True)
    nav = models.DecimalField(max_digits=20, decimal_places=6, null=True)
    repurchase_price = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    sale_price = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    nav_date = models.DateField(db_index=True)
    raw_line = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["scheme_code", "nav_date"]),
        ]

    def __str__(self):
        return f"{self.scheme_code} | {self.scheme_name} | {self.nav_date}"


class EmailSubscriber(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, db_index=True)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        self.email = (self.email or "").strip().lower()
        m = self.mobile_number or ""
        m = re.sub(r"\s+", " ", m).strip()
        self.mobile_number = m or None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} <{self.email}>"


class BlogPost(models.Model):
    heading = models.CharField(max_length=255, db_index=True)
    small_content = models.CharField(max_length=500)
    full_content = models.TextField()
    blog_type = models.CharField(max_length=120, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.heading} ({self.blog_type})"


class BlogRotationState(models.Model):
    singleton_key = models.CharField(max_length=32, unique=True, default="featured")
    ordered_blog_ids = models.JSONField(default=list, blank=True)
    cursor = models.PositiveIntegerField(default=0)
    cycle_started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Blog rotation state: {self.singleton_key}"


class MarketSnapshot(models.Model):
    snapshot_date = models.DateField(unique=True, db_index=True)
    gold_price = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    silver_price = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    crude_oil_price = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    bitcoin_price = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    nifty_50_value = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    sensex_value = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    usd_inr_rate = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-snapshot_date", "-created_at"]

    def __str__(self):
        return f"Market snapshot for {self.snapshot_date}"


class MutualFundDataUpload(models.Model):
    PERIOD_CHOICES = [
        ("Greater than 1 Year", "Greater than 1 Year"),
        ("Less than 1 Year", "Less than 1 Year"),
    ]
    category = models.CharField(max_length=255, help_text="e.g. Childrens Fund")
    period = models.CharField(max_length=100, choices=PERIOD_CHOICES)
    file = models.FileField(upload_to="uploads/mutual_funds/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category} - {self.period} (Uploaded: {self.uploaded_at.date()})"


class MutualFundPerformance(models.Model):
    category = models.CharField(max_length=255, db_index=True)
    period = models.CharField(max_length=100, db_index=True)
    scheme_name = models.CharField(max_length=512)
    nav = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    launch_date = models.DateField(null=True, blank=True)
    aum_crore = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True
    )
    ber_percent = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    ter_percent = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    ytd_return = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    return_1w = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    return_1m = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    return_3m = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    return_6m = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    return_1yr = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    rank_1yr = models.CharField(max_length=50, null=True, blank=True)
    return_2yr = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    rank_2yr = models.CharField(max_length=50, null=True, blank=True)
    return_3yr = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    rank_3yr = models.CharField(max_length=50, null=True, blank=True)
    return_5yr = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    rank_5yr = models.CharField(max_length=50, null=True, blank=True)
    return_10yr = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    rank_10yr = models.CharField(max_length=50, null=True, blank=True)
    fund_manager = models.CharField(max_length=512, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["category", "period"]),
        ]

    def __str__(self):
        return f"{self.scheme_name} ({self.category} - {self.period})"
