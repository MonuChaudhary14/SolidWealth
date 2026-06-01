from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		('api', '0004_blogrotationstate'),
	]

	operations = [
		migrations.AddField(
			model_name='emailsubscriber',
			name='mobile_number',
			field=models.CharField(blank=True, max_length=20, null=True),
		),
	]