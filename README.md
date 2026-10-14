# MCA 2026 Corporate Intelligence Railway Scraper

High-throughput, proxy-rotated corporate intelligence and contact extraction pipeline targeting Indian companies incorporated under the Ministry of Corporate Affairs (MCA).

## 🚀 Key Features

- **17-Field Master Intelligence Profile:**
  1. Corporate Identity Number (CIN)
  2. Legal Company Name
  3. Incorporation Date
  4. Company Class
  5. Industrial Classification
  6. Registered State
  7. Registered Office Address
  8. Authorized Capital (INR)
  9. Paid-up Capital (INR)
  10. Official Corporate Website
  11. Verified Corporate Email
  12. **Company Contact Number** *(Standardized Indian Mobile, Landline, Toll-Free)*
  13. Web Contact Form URL
  14. Employee Strength / Headcount
  15. Key Leadership (Directors / CEO / Key Stakeholders)
  16. Official LinkedIn Company Page
  17. Official Instagram Profile

- **Proxy-First High Throughput:** Designed for pools of 90–100+ rotating residential/datacenter proxies.
- **Resilient Instant Checkpoints:** Automatically detects and skips already enriched companies on container reboot.
- **Docker & Cloud Ready:** Tailored for 24/7 continuous deployment on **Railway** with persistent storage support.

## 🛠️ Deployment on Railway

1. Connect this repository to your **Railway** project.
2. Railway detects the `Dockerfile` and builds the Chromium-ready Linux environment automatically.
3. Configure environment variables in Railway:
   - `CONCURRENCY`: `25`
   - `PROXIES_LIST`: *(Optional: Paste proxy list if not using `proxies.txt`)*
4. Set Restart Policy to `Always` to ensure continuous 24/7 operation.

## 📊 Local Usage

```bash
# Run with 20 concurrent workers
python -u run_2026_enrichment.py --concurrency 20

# Generate quality audit and lead yield statistics
python stats_2026_enriched.py
```
