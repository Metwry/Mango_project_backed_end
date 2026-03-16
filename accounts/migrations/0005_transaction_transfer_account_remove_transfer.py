from django.db import migrations, models


def migrate_transfer_rows(apps, schema_editor):
    Transfer = apps.get_model("accounts", "Transfer")
    Transaction = apps.get_model("accounts", "Transaction")
    db_alias = schema_editor.connection.alias

    duplicate_transaction_ids: set[int] = set()
    transfers = (
        Transfer.objects
        .using(db_alias)
        .select_related("to_account")
        .all()
    )

    for transfer in transfers.iterator():
        if not transfer.out_transaction_id:
            changed = False
            for tx_id in (
                transfer.in_transaction_id,
                transfer.reversed_out_transaction_id,
                transfer.reversed_in_transaction_id,
            ):
                if tx_id:
                    duplicate_transaction_ids.add(tx_id)
            if transfer.in_transaction_id is not None:
                transfer.in_transaction_id = None
                changed = True
            if transfer.reversed_out_transaction_id is not None:
                transfer.reversed_out_transaction_id = None
                changed = True
            if transfer.reversed_in_transaction_id is not None:
                transfer.reversed_in_transaction_id = None
                changed = True
            if changed:
                transfer.save(
                    update_fields=[
                        "in_transaction",
                        "reversed_out_transaction",
                        "reversed_in_transaction",
                    ]
                )
            continue

        out_tx = Transaction.objects.using(db_alias).get(pk=transfer.out_transaction_id)
        out_tx.transfer_account_id = transfer.to_account_id
        out_tx.amount = transfer.amount
        out_tx.counterparty = transfer.to_account.name if transfer.to_account_id else out_tx.counterparty
        out_tx.category_name = "转账"
        note = str(getattr(transfer, "note", "") or "").strip()
        out_tx.remark = note[:16] if note else ""
        update_fields = ["transfer_account", "amount", "counterparty", "category_name", "remark"]

        if transfer.reversed_at and out_tx.reversed_at != transfer.reversed_at:
            out_tx.reversed_at = transfer.reversed_at
            update_fields.append("reversed_at")

        out_tx.save(update_fields=update_fields)

        for tx_id in (
            transfer.in_transaction_id,
            transfer.reversed_out_transaction_id,
            transfer.reversed_in_transaction_id,
        ):
            if tx_id and tx_id != transfer.out_transaction_id:
                duplicate_transaction_ids.add(tx_id)

        transfer.in_transaction_id = None
        transfer.reversed_out_transaction_id = None
        transfer.reversed_in_transaction_id = None
        transfer.save(
            update_fields=[
                "in_transaction",
                "reversed_out_transaction",
                "reversed_in_transaction",
            ]
        )

    if duplicate_transaction_ids:
        (
            Transaction.objects
            .using(db_alias)
            .filter(id__in=sorted(duplicate_transaction_ids))
            .delete()
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("accounts", "0004_alter_accounts_unique_together"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="transfer_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="incoming_transfer_transactions",
                to="accounts.accounts",
            ),
        ),
        migrations.RunPython(migrate_transfer_rows, migrations.RunPython.noop),
        migrations.DeleteModel(
            name="Transfer",
        ),
    ]
