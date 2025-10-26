import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://127.0.0.1:2999/liveclientdata/allgamedata"
try:
    r = requests.get(url, verify=False, timeout=1)
    print("status:", r.status_code)
    print(r.text[:400])
except Exception as e:
    print("error:", e)
