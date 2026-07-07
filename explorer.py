import requests
import zipfile
import io
import json

url = "https://download.open.fda.gov/drug/event/2004q3/drug-event-0002-of-0005.json.zip"
print(f"Downloading a small sample partition: {url}")
resp = requests.get(url, timeout=30)
if resp.status_code == 200:
    print("Download completed. Unzipping and parsing JSON...")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        json_file = zf.namelist()[0]
        with zf.open(json_file) as jf:
            payload = json.load(jf)
            results = payload.get("results", [])
            print(f"Loaded {len(results)} records.")
            if results:
                print("\nSample record keys:")
                sample = results[0]
                for k, v in sample.items():
                    val_type = type(v).__name__
                    if isinstance(v, (dict, list)):
                        print(f" - {k} ({val_type}): {list(v.keys()) if isinstance(v, dict) else (f'list of {type(v[0]).__name__}' if v else 'empty list')}")
                    else:
                        print(f" - {k} ({val_type}): {v}")
                
                print("\n--- Detailed structure of patient: ---")
                patient = sample.get("patient", {})
                for k, v in patient.items():
                    val_type = type(v).__name__
                    print(f"   - {k} ({val_type}): {list(v.keys()) if isinstance(v, dict) else (f'list of {type(v[0]).__name__}' if v else 'empty list')}")
                    if k == "drug" and isinstance(v, list) and v:
                        print("\n     * Sample drug keys:")
                        for dk, dv in v[0].items():
                            print(f"       - {dk} ({type(dv).__name__})")
                            if dk == "openfda":
                                print(f"         - openfda keys: {list(dv.keys())}")
                    if k == "reaction" and isinstance(v, list) and v:
                        print("\n     * Sample reaction keys:")
                        for rk, rv in v[0].items():
                            print(f"       - {rk} ({type(rv).__name__})")
            else:
                print("No records found in the JSON.")
else:
    print(f"Download failed, status: {resp.status_code}")