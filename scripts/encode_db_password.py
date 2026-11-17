"""URL-encode a database password for DATABASE_URL. Input is hidden; output is printed locally only."""
import getpass
import urllib.parse

password = getpass.getpass("DB password (hidden): ")
print(urllib.parse.quote(password, safe=""))
