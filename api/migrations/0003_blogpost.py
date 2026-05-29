from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		('api', '0002_emailsubscriber'),
	]

	operations = [
		migrations.CreateModel(
			name='BlogPost',
			fields=[
				('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
				('heading', models.CharField(db_index=True, max_length=255)),
				('small_content', models.CharField(max_length=500)),
				('full_content', models.TextField()),
				('blog_type', models.CharField(db_index=True, max_length=120)),
				('created_at', models.DateTimeField(auto_now_add=True)),
				('updated_at', models.DateTimeField(auto_now=True)),
			],
			options={
				'ordering': ['-created_at', '-id'],
			},
		),
	]