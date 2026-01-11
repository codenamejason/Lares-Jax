"""Google Calendar integration tools."""

import os
from datetime import datetime, timedelta
from typing import List, Optional

import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = structlog.get_logger()

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]

def get_calendar_service():
    """Get authenticated Google Calendar service."""
    creds = None

    # Load token from environment variable
    token_json = os.getenv('GOOGLE_CALENDAR_TOKEN_JSON')
    if token_json:
        try:
            import json
            creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        except Exception as e:
            log.warning("Failed to load token from env var", error=str(e))

    # Refresh or create new credentials if needed
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Load credentials from individual environment variables
            client_id = os.getenv('GOOGLE_CALENDAR_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CALENDAR_CLIENT_SECRET')

            if not client_id or not client_secret:
                raise Exception("Google Calendar credentials not found. Set GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET")

            try:
                # Construct client config manually
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": ["http://localhost"]
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                log.error("Failed to create credentials from env vars", error=str(e))
                raise Exception("Invalid Google Calendar credentials")

        # Log that we got new credentials
        log.info("New Google Calendar token obtained")

    return build('calendar', 'v3', credentials=creds)

def list_upcoming_events(max_results: int = 10, calendar_id: str = 'primary') -> str:
    """List upcoming calendar events."""
    try:
        service = get_calendar_service()

        # Get events from now onwards
        now = datetime.utcnow().isoformat() + 'Z'

        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        if not events:
            return "No upcoming events found."

        lines = [f"📅 Upcoming Events ({len(events)}):", ""]

        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            start_str = start_dt.strftime('%Y-%m-%d %H:%M')

            summary = event.get('summary', 'Untitled Event')
            lines.append(f"• {start_str}: {summary}")

        return "\n".join(lines)

    except HttpError as e:
        log.error("google_calendar_api_error", error=str(e))
        return f"Google Calendar API error: {e}"
    except Exception as e:
        log.error("calendar_list_failed", error=str(e))
        return f"Error listing events: {e}"

def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    calendar_id: str = 'primary'
) -> str:
    """Create a new calendar event."""
    try:
        service = get_calendar_service()

        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'America/New_York',  # Adjust timezone as needed
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'America/New_York',
            },
        }

        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event
        ).execute()

        log.info("calendar_event_created", event_id=created_event['id'], summary=summary)
        return f"✅ Event created: {summary} (ID: {created_event['id']})"

    except HttpError as e:
        log.error("google_calendar_create_error", error=str(e))
        return f"Google Calendar API error: {e}"
    except Exception as e:
        log.error("calendar_create_failed", error=str(e))
        return f"Error creating event: {e}"

def search_events(query: str, max_results: int = 10, calendar_id: str = 'primary') -> str:
    """Search for events containing the query string."""
    try:
        service = get_calendar_service()

        events_result = service.events().list(
            calendarId=calendar_id,
            q=query,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        if not events:
            return f"No events found matching: {query}"

        lines = [f"🔍 Events matching '{query}' ({len(events)}):", ""]

        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            start_str = start_dt.strftime('%Y-%m-%d %H:%M')

            summary = event.get('summary', 'Untitled Event')
            lines.append(f"• {start_str}: {summary}")

        return "\n".join(lines)

    except HttpError as e:
        log.error("google_calendar_search_error", error=str(e))
        return f"Google Calendar API error: {e}"
    except Exception as e:
        log.error("calendar_search_failed", error=str(e))
        return f"Error searching events: {e}"
