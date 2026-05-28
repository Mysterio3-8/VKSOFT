# Summary of Changes: Token Error Handling in Download Worker

## Problem
The download worker (`workers/download.py`) was not properly handling invalid VK API token errors (error codes 5 and 28). When a token became invalid, the worker would log the error and break out of the loop, but it would not:
2. Set `is_downloading = False` to properly stop the worker
3. Provide consistent error handling compared to other workers (publish.py and monitor.py)

## Solution
Updated `workers/download.py` to handle invalid token errors consistently with other workers:

### Changes Made

1. **Added import for `send_critical_alert`** (line 19):
   ```python
   from vk.api import get_vk_api, vk_call_safe, normalize_owner_id, get_best_photo_url, send_critical_alert
   ```

2. **Enhanced error handling in `_download_source` function** (lines 55-62):
   ```python
   except vk_api.exceptions.ApiError as e:
       code = getattr(e, 'code', 0)
       msg = f'VK API (Р·Р°РіСЂСѓР·РєР°) РѕС€РёР±РєР° {code}: {e}'
       app_state.add_log(msg, 'error')
       if code in (5, 28):
           send_critical_alert(f'РўРѕРєРµРЅ VK РЅРµРґРµР№СЃС‚РІРёС‚РµР»РµРЅ (РєРѕРґ {code}). Р—Р°РіСЂСѓР·РєР° РѕСЃС‚Р°РЅРѕРІР»РµРЅР°.')
           app_state.is_downloading = False
       break
   ```

### Error Codes Handled
- **Code 5**: User authorization failed (invalid access_token)
- **Code 28**: Token expired or invalid

### Behavior
When a token error (code 5 or 28) is detected:
2. `app_state.is_downloading` is set to `False` to stop the worker
3. The error is logged in the application logs
4. The worker breaks out of the download loop

### Consistency with Other Workers
This implementation now matches the error handling in:
- `workers/publish.py` (lines 199-210)
- `workers/monitor.py` (lines 300-306)

All three workers now handle invalid token errors consistently.

## Testing
The changes were verified to ensure:
- `send_critical_alert` is properly imported
- Error codes 5 and 28 are checked
- Critical alert is sent for invalid tokens
- `is_downloading` is set to `False` on token error

## Impact
- The download worker will properly stop when encountering token errors
- Consistent error handling across all workers (download, publish, monitor)
