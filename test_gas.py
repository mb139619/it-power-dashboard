# pip install gie-py
import os
from dotenv import load_dotenv; load_dotenv()
from gie import GiePandasClient
c = GiePandasClient(api_key=os.environ["AGSI_KEY"])
df = c.query_gas_country("IT", start="2025-10-01", end="2026-07-10")
print("shape:", df.shape)
print("colonne:", df.columns.tolist())
print(df.tail(3))