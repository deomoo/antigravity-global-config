---
name: playwright-selenium-office-scraper
description: Helpers and templates for robust Playwright and Selenium web automation, geofence bypassing, and NextAuth session extraction.
---

# Playwright & Selenium Office Scraper Skill

This skill provides templates and heuristics for bypassing geofences, handling slow SPA interfaces, and extracting NextAuth API sessions for Thailand Post automated tasks.

## 1. Geolocation Geofence Override (SAP Fiori)

When automating SAP Fiori portals that enforce geographical limits (such as Na Haeo Post Office), use this script to inject custom coords before the document loads.

### Playwright Python:
```python
async def login_with_geofence(context, page, url):
    # Grant geolocation permissions to the browser context
    await context.grant_permissions(["geolocation"], origin=url)
    
    # Override Geolocation coordinates (Na Haeo PO: 17.480183, 101.070120)
    await context.set_geolocation({"latitude": 17.480183, "longitude": 101.070120, "accuracy": 10})
    
    # Inject geolocation spoofing directly on page document load
    await page.add_script_to_evaluate_on_new_document("""
        const mockCoords = {
            latitude: 17.480183,
            longitude: 101.070120,
            accuracy: 10,
            altitude: null,
            altitudeAccuracy: null,
            heading: null,
            speed: null
        };
        navigator.geolocation.getCurrentPosition = (success) => {
            success({ coords: mockCoords, timestamp: Date.now() });
        };
        navigator.geolocation.watchPosition = (success) => {
            success({ coords: mockCoords, timestamp: Date.now() });
            return 1;
        };
    """)
    await page.goto(url)
```

## 2. Multi-Target SPA Click Retries

SPA buttons (such as SAP Fiori check-in/out) sometimes ignore standard clicks. Implement a retry loop that combines JS clicks, element clicks, and action movements.

```python
async def click_stubborn_button(page, selector, max_retries=3):
    for attempt in range(max_retries):
        try:
            # 1. Native Click
            await page.click(selector, timeout=2000)
            return True
        except Exception:
            try:
                # 2. JS Direct Click (Fallback)
                await page.evaluate(f'document.querySelector("{selector}").click()')
                return True
            except Exception:
                # 3. Wait and retry
                await asyncio.sleep(1)
    return False
```

## 3. NextAuth Session Extraction (Direct REST API)

For Parcelflow or other NextAuth web dashboards, bypass browser automation slowness by extracting the JWT token and calling endpoints via API.

```python
import httpx

def get_direct_api_data(username, password, login_url, data_url):
    with httpx.Client(verify=False) as client:
        # Step 1: POST to NextAuth credentials endpoint
        login_res = client.post(
            f"{login_url}/api/auth/callback/credentials",
            data={"username": username, "password": password, "redirect": "false", "json": "true"}
        )
        
        # Step 2: Extract Session Cookies
        session_res = client.get(f"{login_url}/api/auth/session")
        token = session_res.json().get("accessToken")
        
        # Step 3: Query target API directly with Authorization header
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(data_url, headers=headers)
        return resp.json()
```
