import asyncio
import os
import sqlite3
from datetime import datetime
from models import User, Transaction, Collection
from sqlalchemy.future import select
from database import AsyncSessionLocal

async def test_collections():
    print("--- Testing Collections & Payer logic ---")
    async with AsyncSessionLocal() as session:
        # 1. Create User
        user = User(telegram_id=123456789, name="Test User", role="admin")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"User created: {user.name} (ID: {user.id})")

        # 2. Create Collection (Excursion)
        coll = Collection(name="Экскурсия в Планетарий")
        session.add(coll)
        await session.commit()
        await session.refresh(coll)
        print(f"Collection created: {coll.name} (ID: {coll.id})")

        # 3. Add Income (from child: Ivan)
        tx_in = Transaction(
            type="income",
            amount=1000.0,
            collection_id=coll.id,
            payer_name="Иванов Иван",
            category="Взнос",
            created_by=user.id,
            user_id=user.id
        )
        session.add(tx_in)
        await session.commit()
        print(f"Income added: 1000 for {tx_in.payer_name}")

        # 4. Add Expense (from Excursion fund)
        tx_out = Transaction(
            type="expense",
            amount=400.0,
            collection_id=coll.id,
            category="Билеты",
            created_by=user.id
        )
        session.add(tx_out)
        await session.commit()
        print(f"Expense added: 400 from {coll.name}")

        # 5. Verify Balance for this collection
        # (This logic is what server.py should do)
        res_in = await session.execute(select(Transaction.amount).where(Transaction.collection_id == coll.id, Transaction.type == "income"))
        total_in = sum(res_in.scalars().all())
        
        res_out = await session.execute(select(Transaction.amount).where(Transaction.collection_id == coll.id, Transaction.type == "expense"))
        total_out = sum(res_out.scalars().all())
        
        balance = total_in - total_out
        print(f"Collection Balance: {balance} (Expected: 600.0)")
        
        if balance == 600.0:
            print("[SUCCESS] Collection balance calculation logic verified.")
        else:
            print("[FAILURE] Balance mismatch!")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_collections())
