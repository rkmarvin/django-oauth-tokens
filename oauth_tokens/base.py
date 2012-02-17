from django.conf import settings
from tyoi.oauth2 import AccessTokenRequest, AccessTokenRequestError, AccessTokenResponseError
from tyoi.oauth2.grants import AuthorizationCode, ClientCredentials
from tyoi.oauth2.authenticators import ClientPassword
from urlparse import urlparse
import requests
import logging

log = logging.getLogger('oauth_tokens')

class BaseAccessToken(object):

    cookies = None

    def __init__(self):
        self.client_id = self.get_setting('client_id')
        self.client_secret = self.get_setting('client_secret')
        self.scope = self.get_setting('scope')
        self.username = self.get_setting('username')
        self.password = self.get_setting('password')
        self.redirect_uri = self.get_setting('redirect_uri')
        self.return_to = self.get_setting('redirect_uri')

    def get_setting(self, key):
        return getattr(settings, 'OAUTH_TOKENS_%s_%s' % (self.provider.upper(), key.upper()))

    def parse_auth_form(self, page_content):
        '''
        Parse page with auth form and return tuple with (method, form action, form submit parameters)
        '''
        raise NotImplementedError()

    def parse_permissions_form(self, page_content):
        '''
        Parse page with permissions form and return tuple with (method, form action, form submit parameters)
        '''
        raise NotImplementedError()

    def authorize(self):
        '''
        Authorize and set self.cookies for next requests and return response of last request
        '''
        auth_uri = AuthorizationCode.build_auth_uri(
            endpoint = self.authenticate_url,
            client_id = self.client_id,
            scope = self.scope,
            redirect_uri = self.redirect_uri
        )
        log.debug(auth_uri)

        response = requests.get(auth_uri)

        log.debug('Response form dict: %s' % response.__dict__)
        log.debug('Response form content: %s' % response.content)

        method, action, data = self.parse_auth_form(response.content)

        # submit auth form data
        response = requests.post(action, data)

        log.debug('Response auth dict: %s' % response.__dict__)
        log.debug('Response auth location: %s' % response.headers['location'])

        self.cookies = response.cookies

        return response

    def authorized_request(self, method='get', **kwargs):

        if method not in ['get','post']:
            raise ValueError('Only `get` and `post` are allowed methods')

        if not self.cookies:
            self.authorize()

        if self.cookies:
            return getattr(requests, method)(cookies=self.cookies, **kwargs)
        else:
            raise ValueError('Cookies for authorized request are empty')

    def get(self):
        '''
        Get new token from provider
        '''
        response = self.authorize()

        response = self.authorized_request(url=response.headers['location'])

        log.debug('Response redirect dict: %s' % response.__dict__)
        log.debug('Response redirect content: %s' % response.content)

        params = dict([part.split('=') for part in urlparse(response.url)[4].split('&')])
        if 'code' not in params:
            # it's neccesary additionally to approve requested permissions
            method, approve_url, data = self.parse_permissions_form(response.content)
#            approve_url = 'https://oauth.vkontakte.ru/grant_access?hash=a6c75e8c325807e0e5&client_id=2735668&settings=32768&redirect_uri=http%3A%2F%2Fads.movister.ru%2F&response_type=code&state=&token_type=0'

            log.debug('Grant url: %s' % approve_url)

            response = requests.get(approve_url, cookies=response.cookies)

            log.debug('Response token dict: %s' % response.__dict__)
            log.debug('Response token content: %s' % response.content)

            params = dict([part.split('=') for part in urlparse(response.url)[4].split('&')])
            if 'code' not in params:
                raise Exception("Vkontakte OAuth response didn't return code parameter")

        code = params['code']
        log.debug('Code: %s' % code)

        grant = AuthorizationCode(code, self.return_to)
#       grant = ClientCredentials(scope='32768')
        authenticator = ClientPassword(self.client_id, self.client_secret)
        oauth_request = AccessTokenRequest(authenticator, grant, self.access_token_url)

        try:
            token = oauth_request.send(self.response_decoder)
            token.scope = ','.join(self.scope)
            return token
        except AccessTokenRequestError, ex:
            log.error('Invalid response from oauth provider [code=%s]' % ex.error_code)
            log.error(u'[start]%s[end]' % (ex.error_description or ex.error_code_description))
            return False
        except AccessTokenResponseError, ex:
            log.error('Invalid response from oauth provider: %s' % ex.message)
            return False
        except Exception, e:
            log.error('Error: %s' % e)
            return False

        return False