#!/usr/bin/env python
import json
import traceback
import urllib
import sys
from jwkest.jwe import JWE
from oic.utils.authn.user import NoSuchAuthentication, ToOld, TamperAllert
from oic.utils.time_util import utc_time_sans_frac
from oic.utils.keyio import KeyBundle, key_export

from requests import ConnectionError

from oic.oauth2.message import ErrorResponse
from oic.oauth2.message import by_schema
from oic.oauth2.message import MessageException
from oic.oic.message import RefreshAccessTokenRequest
from oic.oic.message import AuthorizationRequest, Claims
from oic.oic.message import IdToken
from oic.oic.message import OpenIDSchema
from oic.oic.message import RegistrationResponse
from oic.oic.message import AuthorizationResponse
from oic.oic.message import AuthorizationErrorResponse
from oic.oic.message import OpenIDRequest
from oic.oic.message import AccessTokenResponse
from oic.oic.message import AccessTokenRequest
from oic.oic.message import TokenErrorResponse
from oic.oic.message import SCOPE2CLAIMS
from oic.oic.message import RegistrationRequest
from oic.oic.message import ClientRegistrationErrorResponse
from oic.oic.message import DiscoveryRequest
from oic.oic.message import ProviderConfigurationResponse
from oic.oic.message import DiscoveryResponse

from jwkest import jws, jwe
from jwkest.jws import alg2keytype

__author__ = 'rohe0002'

import random
import urlparse
import hmac
import time
import hashlib
import logging

from oic.oauth2.provider import Provider as AProvider

from oic.utils.http_util import Response
from oic.utils.http_util import Redirect
from oic.utils.http_util import BadRequest
from oic.utils.http_util import Unauthorized

from oic.oauth2 import MissingRequiredAttribute
from oic.oauth2 import rndstr

from oic.oic import Server

from oic.oauth2.exception import *

logger = logging.getLogger(__name__)

SWD_ISSUER = "http://openid.net/specs/connect/1.0/issuer"
STR = 5 * "_"


#noinspection PyUnusedLocal
def devnull(txt):
    pass


#noinspection PyUnusedLocal
def do_authorization(user):
    return ""


def secret(seed, sid):
    csum = hmac.new(seed, digestmod=hashlib.sha224)
    csum.update("%s" % time.time())
    csum.update("%f" % random.random())
    csum.update(sid)
    return csum.hexdigest()

#def update_info(aresp, sdict):
#    for prop in aresp._schema["param"].keys():
#        try:
#            aresp[prop] = sdict[prop]
#        except KeyError:
#            pass


def code_token_response(**kwargs):
    _areq = kwargs["areq"]
    _scode = kwargs["scode"]
    _sdb = kwargs["sdb"]

    aresp = AuthorizationResponse()

    for key in ["state", "nonce", "scope"]:
        try:
            aresp[key] = _areq[key]
        except KeyError:
            pass

    aresp["code"] = _scode

    _dic = _sdb.update_to_token(_scode, issue_refresh=False)
    for prop in AccessTokenResponse.c_param.keys():
        try:
            aresp[prop] = _dic[prop]
        except KeyError:
            pass

    return aresp


def location_url(response_type, redirect_uri, query):
    if response_type in [["code"], ["token"], ["none"]]:
        return "%s?%s" % (redirect_uri, query)
    else:
        return "%s#%s" % (redirect_uri, query)


def construct_uri(item):
    (base_url, query) = item
    if query:
        return "%s?%s" % (base_url, urllib.urlencode(query))
    else:
        return base_url

import socket


class Provider(AProvider):
    def __init__(self, name, sdb, cdb, authn_method, userinfo, authz,
                 client_authn, symkey, urlmap=None, ca_certs="", keyjar=None,
                 hostname=""):

        AProvider.__init__(self, name, sdb, cdb, authn_method, authz,
                           client_authn, symkey, urlmap)
        self.userinfo = userinfo
        self.server = Server(ca_certs=ca_certs)

        if keyjar:
            self.server.keyjar = keyjar

        self.keyjar = self.server.keyjar
        self.endpoints = []
        self.baseurl = ""
        self.cert = []
        self.cert_encryption = []

        if authn_method:
            self.cookie_func = authn_method.create_cookie
        else:
            self.cookie_func = None

        self.cookie_name = "pyoidc"
        self.seed = ""
        self.sso_ttl = 0
        self.test_mode = False
        self.jwks_uri = []

        self.authn_as = None
        self.preferred_id_type = "public"
        self.hostname = hostname or socket.gethostname
        self.register_endpoint = "%s%s" % (self.baseurl, "register")

    def id_token_as_signed_jwt(self, session, loa="2", alg="RS256", code=None,
                               access_token=None, user_info=None):

        logger.debug("Signing alg: %s [%s]" % (alg, alg2keytype(alg)))
        _idt = self.server.make_id_token(session, loa, self.name, alg, code,
                                         access_token, user_info)

        logger.debug("id_token: %s" % _idt.to_dict())
        # My signing key if its RS*, can use client secret if HS*
        if alg.startswith("HS"):
            logger.debug("client_id: %s" % session["client_id"])
            ckey = self.keyjar.get_signing_key(alg2keytype(alg),
                                               session["client_id"])
        else:
            for b in self.keyjar[""]:
                logger.debug("OC3 server keys: %s" % b)
            ckey = self.keyjar.get_signing_key(alg2keytype(alg), "")
        logger.debug("ckey: %s" % ckey)
        _signed_jwt = _idt.to_jwt(key=ckey, algorithm=alg)

        return _signed_jwt

    def _error_response(self, error, descr=None):
        logger.error("%s" % error)
        response = ErrorResponse(error=error, error_description=descr)
        return Response(response.to_json(), content="application/json",
                        status="400 Bad Request")

    def _error(self, error, descr=None):
        response = ErrorResponse(error=error, error_description=descr)
        return Response(response.to_json(), content="application/json",
                        status="400 Bad Request")

    def _authz_error(self, error, descr=None):

        response = AuthorizationErrorResponse(error=error)
        if descr:
            response["error_description"] = descr

        return Response(response.to_json(), content="application/json",
                        status="400 Bad Request")

    def _redirect_authz_error(self, error, redirect_uri, descr=None):
        err = ErrorResponse(error=error)
        if descr:
            err["error_description"] = descr
        location = err.request(redirect_uri)
        return Redirect(location)

    def _verify_redirect_uri(self, areq):
        """
        MUST NOT contain a fragment
        MAY contain query component

        :return: An error response if the redirect URI is faulty otherwise
            None
        """
        try:
            _redirect_uri = urlparse.unquote(areq["redirect_uri"])

            part = urlparse.urlparse(_redirect_uri)
            if part.fragment:
                raise URIError("Contains fragment")

            (_base, _query) = urllib.splitquery(_redirect_uri)
            if _query:
                _query = urlparse.parse_qs(_query)

            match = False
            for regbase, rquery in self.cdb[areq["client_id"]]["redirect_uris"]:
                if _base == regbase or _redirect_uri.startswith(regbase):
                    # every registered query component must exist in the
                    # redirect_uri
                    if rquery:
                        for key, vals in rquery.items():
                            assert key in _query
                            for val in vals:
                                assert val in _query[key]
                    match = True
                    break
            if not match:
                raise RedirectURIError("Doesn't match any registered uris")
            # ignore query components that are not registered
            return None
        except Exception, err:
            logger.error("Faulty redirect_uri: %s" % areq["redirect_uri"])
            try:
                _cinfo = self.cdb[areq["client_id"]]
            except KeyError:
                logger.info("Unknown client: %s" % areq["client_id"])
                raise UnknownClient(areq["client_id"])
            else:
                logger.info("Registered redirect_uris: %s" % _cinfo)
                raise RedirectURIError("Faulty redirect_uri: %s" % err)

    def _parse_openid_request(self, request):
        return OpenIDRequest().from_jwt(request, keyjar=self.keyjar)

    def _parse_id_token(self, id_token, redirect_uri):
        try:
            return IdToken().from_jwt(id_token, keyjar=self.keyjar)
        except Exception, err:
            logger.error("Faulty id_token: %s" % id_token)
            logger.error("Exception: %s" % (err.__class__.__name__,))
            id_token = IdToken().from_jwt(id_token, verify=False)
            logger.error("IdToken: %s" % id_token.to_dict())
            return self._redirect_authz_error("invalid_id_token_object",
                                              redirect_uri)

    def get_redirect_uri(self, areq):
        """ verify that the redirect URI is reasonable

        :param areq: The Authorization request
        :return: Tuple of (redirect_uri, Response instance)
            Response instance is not None of matching redirect_uri failed
        """
        if 'redirect_uri' in areq:
            self._verify_redirect_uri(areq)
            uri = areq["redirect_uri"]
        else:
            raise ParameterError(
                "Missing redirect_uri and more than one or none registered")

        return uri

    def get_sector_id(self, redirect_uri, client_info):
        """
        Pick the sector id given a number of factors
        :param redirect_uri: The redirect_uri used
        :param client_info: Information provided by the client in the
          client registration
        :return: A sector_id or None
        """

        _redirect_uri = urlparse.unquote(redirect_uri)

        part = urlparse.urlparse(_redirect_uri)
        if part.fragment:
            raise ValueError

        (_base, _query) = urllib.splitquery(_redirect_uri)

        sid = ""
        try:
            if _base in client_info["si_redirects"]:
                sid = client_info["sector_id"]
        except KeyError:
            try:
                uit = client_info["subject_type"]
                if uit == "pairwise":
                    sid = _base
            except KeyError:
                pass

        return sid

    def handle_oidc_request(self, areq, redirect_uri):
        if "request_uri" in areq:
            # Do a HTTP get
            try:
                _req = self.server.http_request(areq["request_uri"])
            except ConnectionError:
                return self._authz_error("invalid_request_uri")

            if not _req:
                return self._authz_error("invalid_request_uri")

            try:
                resq = self._parse_openid_request(_req.text)
            except Exception:
                return self._redirect_authz_error(
                    "invalid_openid_request_object", redirect_uri)

            areq["request"] = resq

        return areq

    def required_user(self, areq):
        req_user = ""
        try:
            oidc_req = areq["request"]
            try:
                req_user = oidc_req["claims"]["id_token"]["sub"]["value"]
            except KeyError:
                pass
        except KeyError:
            try:
                req_user = areq["id_token"]["sub"]
            except KeyError:
                pass

        return req_user

    def max_age(self, areq):
        try:
            return areq["request"]["max_age"]
        except KeyError:
            try:
                return areq["max_age"]
            except KeyError:
                return 0

    def re_authenticate(self, areq):
        if "prompt" in areq and "login" in areq["prompt"]:
            if self.authn.done(areq):
                return True

        return False

    def authorization_endpoint(self, request="", cookie=None, **kwargs):
        """ The AuthorizationRequest endpoint

        :param request: The client request
        """

        logger.debug("Request: '%s'" % request)
        # Same serialization used for GET and POST
        try:
            areq = self.server.parse_authorization_request(query=request)
        except MissingRequiredAttribute, err:
            logger.debug("%s" % err)
            return self._error("invalid_request", "%s" % err)
        except KeyError:
            areq = AuthorizationRequest().deserialize(request, "urlencoded")
            # verify the redirect_uri
            try:
                self.get_redirect_uri(areq)
            except (RedirectURIError, ParameterError), err:
                return self._error("invalid_request", "%s" % err)
        except Exception, err:
            message = traceback.format_exception(*sys.exc_info())
            logger.error(message)
            logger.debug("Bad request: %s (%s)" % (err, err.__class__.__name__))
            return BadRequest("%s" % err)

        if not areq:
            logger.debug("No AuthzRequest")
            return self._error("invalid_request", "No parsable AuthzRequest")

        logger.debug("AuthzRequest: %s" % (areq.to_dict(),))
        try:
            redirect_uri = self.get_redirect_uri(areq)
        except (RedirectURIError, ParameterError, UnknownClient), err:
            return self._error("invalid_request", "%s" % err)

        try:
            # verify that the request message is correct
            areq.verify()
        except (MissingRequiredAttribute, ValueError), err:
            return self._redirect_authz_error("invalid_request", redirect_uri,
                                              "%s" % err)

        areq = self.handle_oidc_request(areq, redirect_uri)
        logger.debug("AuthzRequest+oidc_request: %s" % (areq.to_dict(),))

        req_user = self.required_user(areq)

        logger.debug("Cookie: %s" % cookie)
        try:
            identity = self.authn.authenticated_as(cookie,
                                                   max_age=self.max_age(areq))
        except (NoSuchAuthentication, ToOld, TamperAllert):
            identity = None

        authn_args = {"query": request, "as_user": req_user}

        cinfo = self.cdb[areq["client_id"]]
        for attr in ["policy_url", "logo_url"]:
            try:
                authn_args[attr] = cinfo[attr]
            except KeyError:
                pass

        # To authenticate or Not
        if identity is None:  # No!
            if "prompt" in areq and "none" in areq["prompt"]:
                # Need to authenticate but not allowed
                return self._redirect_authz_error("login_required",
                                                  redirect_uri)
            else:
                return self.authn(**authn_args)
        else:
            if self.re_authenticate(areq):
                # demand re-authentication
                return self.authn(**authn_args)
            else:
                # I get back a dictionary
                user = identity["uid"]
                if req_user and req_user != user:
                    logger.debug("Wanted to be someone else!")
                    if "prompt" in areq and "none" in areq["prompt"]:
                        # Need to authenticate but not allowed
                        return self._redirect_authz_error("login_required",
                                                          redirect_uri)
                    else:
                        return self.authn(**authn_args)

        logger.debug("- authenticated -")
        logger.debug("AREQ keys: %s" % areq.keys())

        try:
            oidc_req = areq["request"]
        except KeyError:
            oidc_req = None

        sid = self.sdb.create_authz_session(user, areq, oidreq=oidc_req)
        return self.authz_part2(user, areq, sid)

    def userinfo_in_id_token_claims(self, session):
        """
        Put userinfo claims in the id token
        :param session:
        :return:
        """
        itc = self.server.id_token_claims(session)
        if not itc:
            return None

        _claims = by_schema(OpenIDSchema, **itc)

        if _claims:
            return self._collect_user_info(session, {"claims": _claims})
        else:
            return None

    def encrypt(self, payload, client_info, cid, val_type="id_token"):
        """
        Handles the encryption of a payload

        :param payload: The information to be encrypted
        :param client_info: Client information
        :param cid: Client id
        :return: The encrypted information as a JWT
        """

        alg = client_info["%s_encrypted_response_alg" % val_type]
        try:
            enc = client_info["%s_encrypted_response_enc" % val_type]
        except KeyError:
            enc = "A128CBC"

        keys = self.keyjar.get_encrypt_key(owner=cid)
        logger.debug("keys for %s: %s" % (cid, self.keyjar[cid]))
        logger.debug("alg=%s, enc=%s" % (alg, enc))
        logger.debug("Encryption keys for %s: %s" % (cid, keys))

        # use the clients public key for encryption
        _jwe = JWE(payload, alg=alg, enc=enc)
        return _jwe.encrypt(keys, context="public")

    def sign_encrypt_id_token(self, sinfo, client_info, areq, code=None,
                              access_token=None, user_info=None):
        """
        Signed and or encrypt a IDToken

        :param sinfo: Session information
        :param client_info: Client information
        :param areq: The request
        :param code: Access grant
        :param access_token: Access Token
        :param user_info: User information
        :return: IDToken instance
        """

        try:
            alg = client_info["id_token_signed_response_alg"]
        except KeyError:
            alg = "RS256"

        id_token = self.id_token_as_signed_jwt(sinfo, alg=alg,
                                               code=code,
                                               access_token=access_token,
                                               user_info=user_info)

        # Then encrypt
        if "id_token_encrypted_response_alg" in client_info:
            id_token = self.encrypt(id_token, client_info, areq["client_id"],
                                    "id_token")

        return id_token

    def _access_token_endpoint(self, req, **kwargs):

        _sdb = self.sdb
        _log_debug = logger.debug

        client_info = self.cdb[req["client_id"]]

        assert req["grant_type"] == "authorization_code"

        _access_code = req["code"]
        # assert that the code is valid
        if self.sdb.is_revoked(_access_code):
            return self._error(error="access_denied", descr="Token is revoked")

        _info = _sdb[_access_code]

        # If redirect_uri was in the initial authorization request
        # verify that the one given here is the correct one.
        if "redirect_uri" in _info:
            assert req["redirect_uri"] == _info["redirect_uri"]

        _log_debug("All checks OK")

        try:
            _tinfo = _sdb.update_to_token(_access_code)
        except Exception, err:
            logger.error("%s" % err)
            # Should revoke the token issued to this access code
            _sdb.revoke_all_tokens(_access_code)
            return self._error(error="access_denied", descr="%s" % err)

        if "openid" in _info["scope"]:
            userinfo = self.userinfo_in_id_token_claims(_info)
            _idtoken = self.sign_encrypt_id_token(_info, client_info, req,
                                                  user_info=userinfo)
            _sdb.update_by_token(_access_code, "id_token", _idtoken)

        _log_debug("_tinfo: %s" % _tinfo)

        atr = AccessTokenResponse(**by_schema(AccessTokenResponse, **_tinfo))

        _log_debug("access_token_response: %s" % atr.to_dict())

        return Response(atr.to_json(), content="application/json")

    def _refresh_access_token_endpoint(self, req, **kwargs):
        _sdb = self.sdb
        _log_debug = logger.debug

        client_info = self.cdb[req["client_id"]]

        assert req["grant_type"] == "refresh_token"
        rtoken = req["refresh_token"]
        _info = _sdb.refresh_token(rtoken)

        if "openid" in _info["scope"]:
            userinfo = self.userinfo_in_id_token_claims(_info)
            _idtoken = self.sign_encrypt_id_token(_info, client_info, req,
                                                  user_info=userinfo)
            sid = _sdb.token.get_key(rtoken)
            _sdb.update(sid, "id_token", _idtoken)

        _log_debug("_info: %s" % _info)

        atr = AccessTokenResponse(**by_schema(AccessTokenResponse, **_info))

        _log_debug("access_token_response: %s" % atr.to_dict())

        return Response(atr.to_json(), content="application/json")

    #noinspection PyUnusedLocal
    def token_endpoint(self, request="", authn=None, **kwargs):
        """
        This is where clients come to get their access tokens

        :param request: The request
        :param authn: Authentication info, comes from HTTP header
        :returns:
        """
        logger.debug("- token -")
        logger.info("token_request: %s" % request)

        req = AccessTokenRequest().deserialize(request, "urlencoded")
        if "refresh_token" in req:
            req = RefreshAccessTokenRequest().deserialize(request, "urlencoded")

        logger.debug("%s: %s" % (req.__class__.__name__, req))

        try:
            resp = self.client_authn(self, req, authn)
        except Exception, err:
            logger.error("Failed to verify client due to: %s" % err)
            resp = False

        if not resp:
            err = TokenErrorResponse(error="unathorized_client")
            return Unauthorized(err.to_json(), content="application/json")

        if isinstance(req, AccessTokenRequest):
            return self._access_token_endpoint(req, **kwargs)
        else:
            return self._refresh_access_token_endpoint(req, **kwargs)


    def _collect_user_info(self, session, userinfo_claims=None):
        """
        Collect information about a user.
        This can happen in two cases, either when constructing an IdToken or
        when returning user info through the UserInfo endpoint

        :param session: Session information
        :param userinfo_claims: user info claims
        :return: User info
        """
        if userinfo_claims is None:
            uic = {}
            for scope in session["scope"]:
                try:
                    claims = dict([(name, None) for name in
                                   SCOPE2CLAIMS[scope]])
                    uic.update(claims)
                except KeyError:
                    pass

            if "oidreq" in session:
                oidreq = OpenIDRequest().deserialize(session["oidreq"], "json")
                logger.debug("OIDREQ: %s" % oidreq.to_dict())
                try:
                    _claims = oidreq["claims"]["userinfo"]
                except KeyError:
                    pass
                else:
                    for key, val in uic.items():
                        if key not in _claims:
                            _claims[key] = val
                    uic = _claims

                if uic:
                    userinfo_claims = Claims(**uic)
                else:
                    userinfo_claims = None
            elif uic:
                userinfo_claims = Claims(**uic)
            else:
                userinfo_claims = None

            logger.debug("userinfo_claim: %s" % userinfo_claims.to_dict())

        logger.debug("Session info: %s" % session)
        info = self.userinfo(session["local_sub"], userinfo_claims)

        info["sub"] = session["sub"]
        logger.debug("user_info_response: %s" % (info,))

        return info

    #noinspection PyUnusedLocal
    def userinfo_endpoint(self, request="", **kwargs):
        """
        :param request: The request in a string format
        """
        try:
            _log_debug = kwargs["logger"].debug
            _log_info = kwargs["logger"].info
        except KeyError:
            _log_debug = logger.debug
            _log_info = logger.info

        _sdb = self.sdb

        if not request or "access_token" not in request:
            _token = kwargs["authn"]
            assert _token.startswith("Bearer ")
            _token = _token[len("Bearer "):]
            logger.debug("Bearer token: '%s'" % _token)
        else:
            uireq = self.server.parse_user_info_request(data=request)
            logger.debug("user_info_request: %s" % uireq)
            _token = uireq["access_token"]

        # should be an access token
        typ, key = _sdb.token.type_and_key(_token)
        _log_debug("access_token type: '%s'" % (typ,))

        try:
            assert typ == "T"
        except AssertionError:
            raise FailedAuthentication("Wrong type of token")

        #_log_info("keys: %s" % self.sdb.keys())
        if _sdb.is_revoked(key):
            return self._error(error="access_denied", descr="Token is revoked")
        session = _sdb[key]

        # Scope can translate to userinfo_claims

        info = OpenIDSchema(**self._collect_user_info(session))

        # Should I return a JSON or a JWT ?
        _cinfo = self.cdb[session["client_id"]]
        if "userinfo_signed_response_alg" in _cinfo:
            algo = _cinfo["userinfo_signed_response_alg"]
            # Use my key for signing
            key = self.keyjar.get_signing_key(alg2keytype(algo), "")
            jinfo = info.to_jwt(key, algo)
            content_type = "application/jwt"
            if "userinfo_encrypted_response_alg" in _cinfo:
                # encrypt with clients public key
                jinfo = self.encrypt(jinfo, _cinfo, session["client_id"],
                                     "userinfo")
        elif "userinfo_encrypted_response_alg" in _cinfo:
            jinfo = self.encrypt(info.to_json(), _cinfo, session["client_id"],
                                 "userinfo")
            content_type = "application/jwt"
        else:
            jinfo = info.to_json()
            content_type = "application/json"

        return Response(jinfo, content=content_type)

    #noinspection PyUnusedLocal
    def check_session_endpoint(self, request, **kwargs):
        """
        """
        try:
            _log_debug = kwargs["logger"].debug
            _log_info = kwargs["logger"].info
        except KeyError:
            _log_debug = logger.debug
            _log_info = logger.info

        if not request:
            _tok = kwargs["authn"]
            if not _tok:
                return self._error(error="access_denied", descr="Illegal token")
            else:
                info = "id_token=%s" % _tok

        if self.test_mode:
            _log_info("check_session_request: %s" % request)
        idt = self.server.parse_check_session_request(query=request)
        if self.test_mode:
            _log_info("check_session_response: %s" % idt.to_dict())

        return Response(idt.to_json(), content="application/json")

    def _verify_url(self, url, urlset):
        part = urlparse.urlparse(url)

        for reg, qp in urlset:
            _part = urlparse.urlparse(reg)
            if part.scheme == _part.scheme and part.netloc == _part.netloc:
                    return True

        return False

    def do_client_registration(self, request, client_id, ignore=None):
        if ignore is None:
            ignore = []

        _cinfo = self.cdb[client_id].copy()
        logger.debug("_cinfo: %s" % _cinfo)

        for key, val in request.items():
            if key not in ignore:
                _cinfo[key] = val

        if "redirect_uris" in request:
            ruri = []
            for uri in request["redirect_uris"]:
                if urlparse.urlparse(uri).fragment:
                    err = ClientRegistrationErrorResponse(
                        error="invalid_configuration_parameter",
                        error_description="redirect_uri contains fragment")
                    return Response(err.to_json(),
                                    content="application/json",
                                    status="400 Bad Request")
                base, query = urllib.splitquery(uri)
                if query:
                    ruri.append((base, urlparse.parse_qs(query)))
                else:
                    ruri.append((base, query))
            _cinfo["redirect_uris"] = ruri

        if "sector_identifier_uri" in request:
            si_url = request["sector_identifier_uri"]
            try:
                res = self.server.http_request(si_url)
            except ConnectionError, err:
                logger.error("%s" % err)
                return self._error_response(
                    "invalid_configuration_parameter",
                    descr="Couldn't open sector_identifier_uri")

            if not res:
                return self._error_response(
                    "invalid_configuration_parameter",
                    descr="Couldn't open sector_identifier_uri")

            logger.debug("sector_identifier_uri => %s" % res.text)

            try:
                si_redirects = json.loads(res.text)
            except ValueError:
                return self._error_response(
                    "invalid_configuration_parameter",
                    descr="Error deserializing sector_identifier_uri content")

            if "redirect_uris" in request:
                logger.debug("redirect_uris: %s" % request["redirect_uris"])
                for uri in request["redirect_uris"]:
                    try:
                        assert uri in si_redirects
                    except AssertionError:
                        return self._error_response(
                            "invalid_configuration_parameter",
                            descr="redirect_uri missing from sector_identifiers"
                        )

            _cinfo["si_redirects"] = si_redirects
            _cinfo["sector_id"] = si_url
        elif "redirect_uris" in request:
            if len(request["redirect_uris"]) > 1:
                # check that the hostnames are the same
                host = ""
                for url in request["redirect_uris"]:
                    part = urlparse.urlparse(url)
                    _host = part.netloc.split(":")[0]
                    if not host:
                        host = _host
                    else:
                        try:
                            assert host == _host
                        except AssertionError:
                            return self._error_response(
                                "invalid_configuration_parameter",
                                descr=
                                "'sector_identifier_uri' must be registered")

        for item in ["policy_url", "logo_url"]:
            if item in request:
                if self._verify_url(request[item], _cinfo["redirect_uris"]):
                    _cinfo[item] = request[item]
                else:
                    return self._error_response(
                        "invalid_configuration_parameter",
                        descr="%s pointed to illegal URL" % item)

        try:
            self.keyjar.load_keys(request, client_id)
            try:
                logger.debug("keys for %s: [%s]" % (
                    client_id,
                    ",".join(["%s" % x for x in self.keyjar[client_id]])))
            except KeyError:
                pass
        except Exception, err:
            logger.error("Failed to load client keys: %s" % request.to_dict())
            err = ClientRegistrationErrorResponse(
                error="invalid_configuration_parameter",
                error_description="%s" % err)
            return Response(err.to_json(), content="application/json",
                            status="400 Bad Request")

        return _cinfo

    def comb_redirect_uris(self, args):
        if "redirect_uris" not in args:
            return

        val = []
        for base, query in args["redirect_uris"]:
            if query:
                val.append("%s?%s" % (base, query))
            else:
                val.append(base)

        args["redirect_uris"] = val

    #noinspection PyUnusedLocal
    def l_registration_endpoint(self, request, authn=None, **kwargs):
        _log_debug = logger.debug
        _log_info = logger.info

        _log_debug("@registration_endpoint")

        request = RegistrationRequest().deserialize(request, "json")

        _log_info("registration_request:%s" % request.to_dict())
        resp_keys = request.keys()

        try:
            request.verify()
        except MessageException, err:
            if "type" not in request:
                return self._error(error="invalid_type", 
                                   descr="%s" % err)
            else:
                return self._error(error="invalid_configuration_parameter",
                                   descr="%s" % err)

        _keyjar = self.server.keyjar

        # create new id och secret
        client_id = rndstr(12)
        while client_id in self.cdb:
            client_id = rndstr(12)

        client_secret = secret(self.seed, client_id)

        _rat = rndstr(32)
        reg_enp = ""
        for endp in self.endpoints:
            if isinstance(endp, RegistrationEndpoint):
                reg_enp = "%s%s" % (self.baseurl, endp.etype)

        self.cdb[client_id] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "registration_access_token": _rat,
            "registration_client_uri": "%s?client_id=%s" % (reg_enp, client_id),
            "client_secret_expires_at": utc_time_sans_frac() + 86400,
            "client_id_issued_at": utc_time_sans_frac()}

        self.cdb[_rat] = client_id

        _cinfo = self.do_client_registration(request, client_id,
                                             ignore=["redirect_uris",
                                                     "policy_url",
                                                     "logo_url"])
        if isinstance(_cinfo, Response):
            return _cinfo

        args = dict([(k, v) for k, v in _cinfo.items()
                     if k in RegistrationResponse.c_param])

        self.comb_redirect_uris(args)
        response = RegistrationResponse(**args)

        self.keyjar.load_keys(request, client_id)

        # Add the key to the keyjar
        if client_secret:
            _kc = KeyBundle([{"kty": "oct", "key": client_secret,
                              "use": "ver"},
                             {"kty": "oct", "key": client_secret,
                              "use": "sig"}])
            try:
                _keyjar[client_id].append(_kc)
            except KeyError:
                _keyjar[client_id] = [_kc]

        self.cdb[client_id] = _cinfo
        _log_info("Client info: %s" % _cinfo)

        logger.debug("registration_response: %s" % response.to_dict())

        return Response(response.to_json(), content="application/json",
                        headers=[("Cache-Control", "no-store")])

    def registration_endpoint(self, request, authn=None, **kwargs):
        return self.l_registration_endpoint(request, authn, **kwargs)

    def read_registration(self, authn, request, **kwargs):
        """
        Read all information this server has on a client.
        Authorization is done by using the access token that was return as
        part of the client registration result.

        :param authn: The Authorization HTTP header
        :param request: The query part of the URL
        :param kwargs: Any other arguments
        :return:
        """

        logger.debug("authn: %s, request: %s" % (authn, request))

        # verify the access token, has to be key into the client information
        # database.
        assert authn.startswith("Bearer ")
        token = authn[len("Bearer "):]

        client_id = self.cdb[token]

        # extra check
        _info = urlparse.parse_qs(request)
        assert _info["client_id"][0] == client_id

        logger.debug("Client '%s' reads client info" % client_id)
        args = dict([(k, v) for k, v in self.cdb[client_id].items()
                     if k in RegistrationResponse.c_param])

        self.comb_redirect_uris(args)
        response = RegistrationResponse(**args)

        return Response(response.to_json(), content="application/json",
                        headers=[("Cache-Control", "no-store")])

    #noinspection PyUnusedLocal
    def providerinfo_endpoint(self, handle="", **kwargs):
        _log_debug = logger.debug
        _log_info = logger.info

        _log_info("@providerinfo_endpoint")
        try:
            _response = ProviderConfigurationResponse(
                issuer=self.baseurl,
                token_endpoint_auth_methods_supported=[
                    "client_secret_post", "client_secret_basic",
                    "client_secret_jwt", "private_key_jwt"],
                scopes_supported=["openid"],
                response_types_supported=["code", "token", "id_token",
                                          "code token", "code id_token",
                                          "token id_token",
                                          "code token id_token"],
                subject_types_supported=["public", "pairwise"],
                grant_types_supported=[
                    "authorization_code", "implicit",
                    "urn:ietf:params:oauth:grant-type:jwt-bearer"],
                claim_types_supported=["normal", "aggregated", "distributed"],
                claims_supported=SCOPE2CLAIMS.keys(),
                claims_parameter_supported="true",
                request_parameter_supported="true",
                request_uri_parameter_supported="true",
                #request_object_algs_supported=["HS256"]
            )

            sign_algs = jws.SIGNER_ALGS.keys()

            for typ in ["userinfo", "id_token", "request_object",
                        "token_endpoint_auth"]:
                _response["%s_signing_alg_values_supported" % typ] = sign_algs

            algs = jwe.SUPPORTED["alg"]
            for typ in ["userinfo", "id_token", "request_object"]:
                _response["%s_encryption_alg_values_supported" % typ] = algs

            encs = jwe.SUPPORTED["enc"]
            for typ in ["userinfo", "id_token", "request_object"]:
                _response["%s_encryption_enc_values_supported" % typ] = encs

            if not self.baseurl.endswith("/"):
                self.baseurl += "/"

            #keys = self.keyjar.keys_by_owner(owner=".")
            if self.jwks_uri:
                _response["jwks_uri"] = self.jwks_uri

            #_log_info("endpoints: %s" % self.endpoints)
            for endp in self.endpoints:
                #_log_info("# %s, %s" % (endp, endp.name))
                _response[endp.name] = "%s%s" % (self.baseurl, endp.etype)

            _log_info("provider_info_response: %s" % (_response.to_dict(),))

            headers = [("Cache-Control", "no-store"), ("x-ffo", "bar")]
            if handle:
                (key, timestamp) = handle
                if key.startswith(STR) and key.endswith(STR):
                    cookie = self.cookie_func(key, self.cookie_name, "pinfo",
                                              self.sso_ttl)
                    headers.append(cookie)

            resp = Response(_response.to_json(), content="application/json",
                            headers=headers)
        except Exception, err:
            message = traceback.format_exception(*sys.exc_info())
            logger.error(message)
            resp = Response(message, content="html/text")

        return resp

    #noinspection PyUnusedLocal
    def discovery_endpoint(self, request, handle=None, **kwargs):
        """
        :param request:
        :param handle:
        """

        _log_debug = logger.debug

        _log_debug("@discovery_endpoint")

        request = DiscoveryRequest().deserialize(request, "urlencoded")
        _log_debug("discovery_request:%s" % (request.to_dict(),))

        try:
            assert request["service"] == SWD_ISSUER
        except AssertionError:
            return BadRequest("Unsupported service")

        # verify that the principal is one of mine

        _response = DiscoveryResponse(locations=[self.baseurl])

        _log_debug("discovery_response:%s" % (_response.to_dict(),))

        headers = [("Cache-Control", "no-store")]
        (key, timestamp) = handle
        if key.startswith(STR) and key.endswith(STR):
            cookie = self.cookie_func(key, self.cookie_name, "disc",
                                      self.sso_ttl)
            headers.append(cookie)

        return Response(_response.to_json(), content="application/json",
                        headers=headers)

    def authz_part2(self, user, areq, sid, **kwargs):
        """
        After the authentication this is where you should end up
        """
        _log_debug = logger.debug
        _log_debug("- in authenticated() -")

        # Do the authorization
        try:
            info = OpenIDSchema(**self._collect_user_info(self.sdb[sid]))
            permission = self.authz(user)
            self.sdb.update(sid, "permission", permission)
        except Exception:
            raise

        _log_debug("response type: %s" % areq["response_type"])

        # create the response
        aresp = AuthorizationResponse()
        try:
            aresp["state"] = areq["state"]
        except KeyError:
            pass

        if "response_type" in areq and \
                len(areq["response_type"]) == 1 and \
                "none" in areq["response_type"]:
            pass
        else:
            if self.sdb.is_revoked(sid):
                return self._error(error="access_denied",
                                   descr="Token is revoked")

            _sinfo = self.sdb[sid]

            try:
                aresp["scope"] = areq["scope"]
            except KeyError:
                pass

            _log_debug("_dic: %s" % _sinfo)

            rtype = set(areq["response_type"][:])
            if "code" in areq["response_type"]:
                #if issue_new_code:
                #    scode = self.sdb.duplicate(_sinfo)
                #    _sinfo = self.sdb[scode]

                _code = aresp["code"] = _sinfo["code"]
                rtype.remove("code")
            else:
                self.sdb[sid]["code"] = None
                _code = None

            if "token" in rtype:
                _dic = self.sdb.update_to_token(issue_refresh=False, key=sid)

                _log_debug("_dic: %s" % _dic)
                for key, val in _dic.items():
                    if key in aresp.parameters() and val is not None:
                        aresp[key] = val

                rtype.remove("token")

            try:
                _access_token = aresp["access_token"]
            except KeyError:
                _access_token = None

            if "id_token" in areq["response_type"]:
                user_info = self.userinfo_in_id_token_claims(_sinfo)
                client_info = self.cdb[areq["client_id"]]

                id_token = self.sign_encrypt_id_token(
                    _sinfo, client_info, areq, code=_code,
                    access_token=_access_token, user_info=user_info)

                aresp["id_token"] = id_token
                _sinfo["id_token"] = id_token
                rtype.remove("id_token")

            if len(rtype):
                return BadRequest("Unknown response type")

        try:
            redirect_uri = self.get_redirect_uri(areq)
        except (RedirectURIError, ParameterError), err:
            return BadRequest("%s" % err)

        # Must not use HTTP unless implicit grant type and native application

        # Use of the nonce is REQUIRED for all requests where an ID Token is
        # returned directly from the Authorization Endpoint
        if "id_token" in aresp:
            try:
                assert "nonce" in areq
            except AssertionError:
                return self._error("invalid_request", "Missing nonce value")

        # so everything went well should set a SSO cookie
        headers = [self.authn.create_cookie(user, typ="sso", ttl=self.sso_ttl)]
        location = aresp.request(redirect_uri)
        logger.debug("Redirected to: '%s' (%s)" % (location, type(location)))
        return Redirect(str(location), headers=headers)

    def key_setup(self, local_path, vault="keys", sig=None, enc=None):
        """
        my keys
        :param local_path: The path to where the JWKs should be stored
        :param vault: Where the private key will be stored
        :param sig: Key for signature
        :param enc: Key for encryption
        :return: A URL the RP can use to download the key.
        """
        self.jwks_uri = key_export(self.baseurl, local_path, vault, self.keyjar,
                                   fqdn=self.hostname, sig=sig, enc=enc)

    def register_endpoint(self, request="", **kwargs):
        pass

# -----------------------------------------------------------------------------


class Endpoint(object):
    etype = ""

    def __init__(self, func):
        self.func = func

    @property
    def name(self):
        return "%s_endpoint" % self.etype

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


class AuthorizationEndpoint(Endpoint):
    etype = "authorization"


class TokenEndpoint(Endpoint):
    etype = "token"


class UserinfoEndpoint(Endpoint):
    etype = "userinfo"


class RegistrationEndpoint(Endpoint) :
    etype = "registration"
