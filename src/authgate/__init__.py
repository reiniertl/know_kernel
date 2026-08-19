"""Authentication gate — MOD-KK-AUTH.

Owns auth.db (users, sessions, remember tokens). Never touches the knowledge
graph in master.db (INV-KK-AUTH-STORE-SEPARATE).
"""
