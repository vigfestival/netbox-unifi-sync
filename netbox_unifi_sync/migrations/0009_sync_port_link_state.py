from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_unifi_sync", "0008_sync_scope_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="globalsyncsettings",
            name="sync_port_link_state",
            field=models.BooleanField(
                default=True,
                help_text="Reflect live port link state: mark a switch/AP port as connected "
                          "in NetBox (and note the negotiated speed) when something is plugged in.",
            ),
        ),
    ]
