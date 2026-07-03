import os
import dotenv
from database_controller import DatabaseController

dotenv.load_dotenv()
db = DatabaseController({
    'host': os.getenv('host'), 'user': os.getenv('user'),
    'password': os.getenv('password'), 'database': os.getenv('database')
})

USER_ID = '1768237004.771031'
conn = db.get_connection()
cursor = conn.cursor()
cursor.execute("SELECT id, reason FROM long_pending WHERE user_id = %s", (USER_ID,))
lps = cursor.fetchall()
for lp in lps:
    print(lp)
    
cursor.execute("SELECT account_name FROM accounts WHERE user_id = %s", (USER_ID,))
print("Accounts:", cursor.fetchall())
