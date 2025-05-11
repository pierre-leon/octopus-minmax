import requests
from queries import *

class QueryService:
    def __init__(self, api_key: str, base_url: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json'
        }
        self.graphql_endpoint = f"{self.base_url}/graphql/"

        self.token = None
        self.token = self._get_token()

    def _get_token(self):
        formatted_token_query = token_query.format(api_key=self.api_key)

        res = self.execute_gql_query(formatted_token_query)
        token = res.get("obtainKrakenToken", {}).get("token")

        if not token:
            raise Exception("Failed to obtain authentication token")

        return token

    def execute_gql_query(self, query: str):
        headers = self.headers.copy()
        if self.token:
           headers["Authorization"] = self.token

        payload = {
            "query": query,
            "variables": {}
        }

        response = requests.post(
            self.graphql_endpoint,
            headers=headers,
            json=payload,
            timeout=60
        )

        if not response.ok:
            raise Exception(f"GQL query failed: {response.status_code}: {response.text}")

        result = response.json()

        if "errors" in result:
            raise Exception(f"GQL errors: {result['errors']}")

        return result.get("data", {})