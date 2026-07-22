import os, requests
from dotenv import load_dotenv; load_dotenv()

k = os.environ.get("TERNA_API_KEY")
s = os.environ.get("TERNA_API_SECRET")
print("key  :", (k[:4]+"..."+k[-3:]) if k else "MANCANTE", "| len:", len(k) if k else 0)
print("secret:", (s[:4]+"..."+s[-3:]) if s else "MANCANTE", "| len:", len(s) if s else 0)
print("spazi/virgolette nella key?  ", repr(k[:2]) if k else "-", repr(k[-2:]) if k else "-")

# chiamata diretta al token endpoint: vogliamo il CORPO della risposta, non solo il 401
r = requests.post("https://api.terna.it/transparency/oauth/accessToken",
                  data={"client_id": k, "client_secret": s, "grant_type": "client_credentials"},
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
print("\nstatus:", r.status_code)
print("body  :", r.text[:400])