import pymongo

def check_db():
    uri = "mongodb+srv://rnnisarg7_db_user:M1mCUWQLm15Ashco@nisarg.csleyfb.mongodb.net/trade-db?appName=Nisarg"
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client["trade-db"]
    collections = db.list_collection_names()
    print(f"Collections found: {collections}")
    for coll in collections:
        count = db[coll].count_documents({})
        print(f"Collection {coll} has {count} documents.")

if __name__ == "__main__":
    check_db()
