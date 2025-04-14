from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class UserLinks(models.Model):
    link = models.TextField(help_text='The link provided by user')
    link_hash = models.CharField(max_length=256, unique=True,
                                 help_text='Unique hash of link, lower cased. Prevent duplicate links.')
    status = models.IntegerField(help_text='Status of this link', null=True)
    content_type = models.CharField(max_length=256, help_text='Content type of response from link')
    stats = models.TextField(help_text='JSON string for link stats - tag/counts')
    fk_user = models.ForeignKey(to=User, on_delete=models.CASCADE)

