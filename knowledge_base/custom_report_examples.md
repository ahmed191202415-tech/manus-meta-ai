# Custom Report Examples

Landing pages by source and device:

```json
{
  "tenant_id": "client@example.com",
  "property_id": "123456789",
  "start_date": "30daysAgo",
  "end_date": "today",
  "dimensions": ["landingPagePlusQueryString", "sessionSourceMedium", "deviceCategory"],
  "metrics": ["sessions", "engagedSessions", "engagementRate", "conversions", "totalRevenue"],
  "limit": 100
}
```

Events:

```json
{
  "tenant_id": "client@example.com",
  "dimensions": ["eventName", "date"],
  "metrics": ["eventCount", "activeUsers"]
}
```
