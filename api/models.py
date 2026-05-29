from django.db import models


class NavEntry(models.Model):
	scheme_code = models.CharField(max_length=64, db_index=True)
	isin = models.CharField(max_length=64, blank=True, null=True, db_index=True)
	scheme_name = models.CharField(max_length=512, db_index=True)
	nav = models.DecimalField(max_digits=20, decimal_places=6, null=True)
	repurchase_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	sale_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	nav_date = models.DateField(db_index=True)
	raw_line = models.TextField(blank=True)

	class Meta:
		indexes = [
			models.Index(fields=['scheme_code', 'nav_date']),
		]

	def __str__(self):
		return f"{self.scheme_code} | {self.scheme_name} | {self.nav_date}"


class EmailSubscriber(models.Model):
	name = models.CharField(max_length=255)
	email = models.EmailField(unique=True, db_index=True)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['name']

	def save(self, *args, **kwargs):
		self.name = (self.name or '').strip()
		self.email = (self.email or '').strip().lower()
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
		ordering = ['-created_at', '-id']

	def __str__(self):
		return f"{self.heading} ({self.blog_type})"


class BlogRotationState(models.Model):
	singleton_key = models.CharField(max_length=32, unique=True, default='featured')
	ordered_blog_ids = models.JSONField(default=list, blank=True)
	cursor = models.PositiveIntegerField(default=0)
	cycle_started_at = models.DateTimeField(null=True, blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f"Blog rotation state: {self.singleton_key}"
