from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ai", "0003_dedupe_aianalysis_add_unique_source"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=models.deletion.CASCADE,
                        related_name="chat_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "ai_chat_session",
                "verbose_name": "AI 会话",
                "verbose_name_plural": "AI 会话",
                "ordering": ["-updated_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ChatMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("USER", "USER"), ("ASSISTANT", "ASSISTANT")], max_length=20)),
                ("content", models.TextField()),
                ("sequence", models.PositiveIntegerField()),
                (
                    "session",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=models.deletion.CASCADE,
                        related_name="messages",
                        to="ai.chatsession",
                    ),
                ),
            ],
            options={
                "db_table": "ai_chat_message",
                "verbose_name": "AI 消息",
                "verbose_name_plural": "AI 消息",
                "ordering": ["session_id", "sequence", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="chatmessage",
            constraint=models.UniqueConstraint(
                fields=("session", "sequence"),
                name="uniq_ai_chat_message_session_sequence",
            ),
        ),
        migrations.AddIndex(
            model_name="chatmessage",
            index=models.Index(fields=["session", "sequence"], name="ai_chat_msg_session_seq_idx"),
        ),
    ]
