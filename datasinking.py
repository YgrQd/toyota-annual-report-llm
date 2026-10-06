import time
import requests

class DataSinkingError(RuntimeError):
    pass

class DataSinkingClient:
    """Official REST API; never log query URLs containing apikey."""
    def __init__(self, key):
        self.key = key
        self.session = requests.Session()
        self.last_request = 0.0

    def get(self, path, **params):
        for attempt in range(3):
            time.sleep(max(0, 0.4 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                r = self.session.get('https://api.datasink.ing' + path,
                    params={**params, 'apikey': self.key}, timeout=(10, 90))
            except requests.RequestException:
                raise DataSinkingError('DataSinking network request failed; URL and credentials suppressed.') from None
            if r.status_code == 429 or r.status_code >= 500:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            if not r.ok:
                raise DataSinkingError(f'DataSinking returned HTTP {r.status_code}; response suppressed.')
            try:
                return r.json()
            except ValueError:
                raise DataSinkingError('Expected a JSON API response.') from None
        raise DataSinkingError('Retry budget exhausted.')

    def stocks(self):
        return self.get('/stocks', exchange='jpx')

    def reports(self):
        # Server ordering is by reporting period, not disclosure date.
        return self.get('/documents', symbol='7203.T', doc_type='annual', order='desc', size=1)

    def sections(self, document_id):
        return self.get(f'/documents/{document_id}/sections')

    def section(self, document_id, title):
        return self.get(f'/documents/{document_id}', section=title)
