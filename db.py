import streamlit as st
from astrapy import DataAPIClient

# Fetch secrets
ASTRA_DB_ID = st.secrets["ASTRA_DB_ID"]
ASTRA_DB_TOKEN = st.secrets["ASTRA_DB_APPLICATION_TOKEN"]
KEYSPACE_NAME = st.secrets["ASTRA_KEYSPACE"]

@st.cache_resource
def get_db():
    # Initialize Astra DB client
    client = DataAPIClient(
        astra_database_id=ASTRA_DB_ID,
        astra_application_token=ASTRA_DB_TOKEN
    )
    # Connect to keyspace
    db = client.get_keyspace(KEYSPACE_NAME)
    return db

db = get_db()

# Collections
collection_names = ["personal_data", "notes"]
for collection in collection_names:
    try:
        db.create_collection(collection)
    except:
        pass

personal_data_collection = db.get_collection("personal_data")
notes_collection = db.get_collection("notes")
