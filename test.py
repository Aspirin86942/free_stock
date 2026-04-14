import gm.api as gm
from pprint import pprint

TOKEN = "316584b8adad4be76baa01479595145fb4203447"

gm.set_token(TOKEN)

rows = gm.current(
    symbols=["SHSE.600036", "SZSE.000001"],
    fields="symbol,price,open,high,low,cum_volume,cum_amount,created_at",
    include_call_auction=False,
)

for row in rows:
    pprint(row)

if __name__ == "__main__":
    pass
