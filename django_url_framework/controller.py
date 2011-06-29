from functools import wraps
from django.http import *
import re
from django.utils.safestring import SafeUnicode
from django_url_framework.helper import ApplicationHelper
from django.utils.translation import ugettext as _
from django.core.xheaders import populate_xheaders
from django.conf.urls.defaults import patterns, url, include

from django_url_framework.exceptions import InvalidActionError
from django_url_framework.exceptions import InvalidControllerError

def get_controller_name(controller_class, with_prefix = True):
    controller_name = None
    if hasattr(controller_class, 'controller_name'):
        controller_name = controller_class.controller_name
    else:
        name_ = [controller_class.__name__[0]]
        prev = ''
        for l in re.sub(r"Controller$",'',controller_class.__name__[1:]):
            if l.isupper() and prev.islower():
                name_.append('_'+l)
            else:
                name_.append(l)
            prev = l
        controller_name = ''.join(name_).lower()
        
    if with_prefix and hasattr(controller_class, 'controller_prefix'):
        controller_name = controller_class.controller_prefix + controller_name
    return controller_name

def autoview_function(site, request, controller_name, controller_class, action_name = 'index', *args, **kwargs):
    error_msg = None
    try:
        # if controller_name in self.controllers:
        # controller_class = self.controllers[controller_name]
        if action_name in get_actions(controller_class):
            helper = ApplicationHelper#self.helpers.get(controller_name, ApplicationHelper)
            return controller_class(site, request, helper)._call_action(action_name, *args, **kwargs)
        else:
            raise InvalidActionError(action_name)
        # else:
            # raise InvalidControllerError()
    # except InvalidControllerError, e:
        # error_msg = _("No such controller: %(controller_name)s") % {'controller_name' : controller_name}
    except InvalidActionError, e:
        error_msg = _("Action '%(action_name)s' not found in controller '%(controller_name)s'") % {'action_name' : e.message, 'controller_name' : controller_name}
        
    raise Http404(error_msg)


def get_controller_urlconf(controller_class, site=None):
    controller_name = get_controller_name(controller_class)
    actions = get_actions(controller_class)
    urlpatterns = patterns('')
    def wrap_call(controller_name, action_name, action_func):
        """Wrapper for the function called by the url."""
        def wrapper(*args, **kwargs):
            request, args = args[0], args[1:]
            return autoview_function(site, request, controller_name, controller_class, action_name, *args, **kwargs)
        return wraps(action_func)(wrapper)
        
    for action_name, action_func in actions.items():
        named_url = '%s_%s' % (get_controller_name(controller_class, with_prefix=False), get_action_name(action_func) )
        named_url = getattr(action_func, 'named_url', named_url)
        replace_dict = {'action':action_name.replace("__","/")}
        wrapped_call = wrap_call(controller_name, action_name, action_func)

        if hasattr(action_func, 'urlconf'):
            """Define custom urlconf patterns for this action."""
            for line in action_func.urlconf:
                new_urlconf = r'^%s$' % line
                urlpatterns += patterns('', url(new_urlconf, wrapped_call, name=named_url), )
        
        if getattr(action_func, 'urlconf_erase', False) == False:
            """Do not generate default URL patterns if we define 'urlconf_erase' for this action."""
            
            if action_name == 'index':
                """No root URL is generated if we have no index action."""
                urlpatterns += patterns('',
                    url(r'^$', wrapped_call, name=named_url),
                    #url(r'(?P<object_id>\d+)/$', wrapped_call, name=named_url)
                    )
            else:
                if hasattr(action_func, 'url_parameters'):
                    arguments = action_func.url_parameters
                    replace_dict['url_parameters'] = arguments
                    urlpatterns += patterns('',
                        url(r'^%(action)s/%(url_parameters)s$' % replace_dict, wrapped_call, name=named_url)
                    )

                else:
                    arguments = action_func.func_code.co_varnames
                    if action_func.func_code.co_argcount==3:
                        replace_dict['object_id_arg_name'] = arguments[2]
                        urlpatterns += patterns('',
                            url(r'^%(action)s/(?P<%(object_id_arg_name)s>\d+)/$' % replace_dict, wrapped_call, name=named_url)
                            )
                
                    urlpatterns += patterns('',
                        url(r'^%(action)s/$' % replace_dict, wrapped_call, name=named_url),
                        )
                
    return urlpatterns
CACHED_ACTIONS = {}

def get_action_name(func, with_prefix = False):
    if callable(func):
        func_name = func.func_name
        if not re.match(r'^[_\-A-Z0-9]',func_name[0]):
            if hasattr(func, 'action_name'):
                func_name = func.action_name
            if with_prefix and hasattr(func, 'action_prefix'):
                func_name = func.action_prefix + func_name
            return func_name
    raise InvalidActionError(func.func_name)

def get_actions(controller, with_prefix = True):
    if isinstance(controller, ActionController):
        controller_cache_key = controller.__class__.__name__ + str(with_prefix)
        controller = controller.__class__
    else:
        controller_cache_key = controller.__name__ + str(with_prefix)
        
    if controller_cache_key not in CACHED_ACTIONS:
        actions = {}
        for func_name in dir(controller):
            func = getattr(controller,func_name)
            if not re.match(r'^[_\-A-Z0-9]',func_name[0]) and callable(func):
                if hasattr(func, 'action_name'):
                    func_name = func.action_name
                if with_prefix and hasattr(func, 'action_prefix'):
                    func_name = func.action_prefix + func_name
                actions[func_name] = func
        CACHED_ACTIONS[controller_cache_key] = actions
    return CACHED_ACTIONS[controller_cache_key]

def get_action_wrapper(site, controller_class, action_name):
    """Possible future helper method..."""
    controller_name = get_controller_name(controller_class)
    actions = get_actions(controller_class)
    def wrap_call(controller_name, action_name, action_func):
        """Wrapper for the function called by the url."""
        def wrapper(*args, **kwargs):
            request, args = args[0], args[1:]
            return autoview_function(site, request, controller_name, controller_class, action_name, *args, **kwargs)
        return wraps(action_func)(wrapper)
    
    if action_name in actions:
        wrapped_call = wrap_call(controller_name, action_name, actions[action_name])
        return wrapped_call
    else:
        raise InvalidActionError(action_name)

class ActionController(object):
    """
    Any function that does not start with a _ will be considered an action.

    Returning a dictionary object from an action will render that dictionary in the
    default template for that action. Returning a string will simply print the string.


    ActionControllers can have the following attributes:

        controller_name
                Set the controller's name
    
        controller_prefix
                Set a prefix for the controller's name, applies even if
                you set controller_name (template name is based on controller_name, sans prefix)
    
        no_subdirectories
                Template files should be named ControllerName_ActionName.html, or
                _ControllerName_ActionName.html in the case of ajax requests.
                
                Default: False
                
        template_prefix
                Directory or filename prefix for template files.
                
                Default: controller name sans prefix
            
        ignore_ajax
                This controller ignores template file name changes based on the ajax nature of a request.
                If this is False, the template file will be prefixed with _ (underscore) for all ajax requests.
                
                Default: False
            
    Actions can have the following function attributes:

        disable_filters
            Disable before_filter and after_filter functions.
    
        template_name
            Force a specific template name
    
        ajax_template_name
            Force a specific template name for AJAX requests
        
        allowed_methods
            An array or tuple of http methods permitted to access this action, can also be a string.

        urlconf
            A custom url configuration for this action, just like in Django's urls.py.
            The custom urlconf applies after the urlconf for the controller.
        
        urlconf_erase
            Whether to erase the default URL-conf for this action and just keep the custom one
            
        url_parameters
            A string representing the argument part of the URL for this action, for instance:
            The action 'user' is given the URL /user/, by adding r'(?P<user_id>\d+)' as the
            url_parameters switch, the URL becomes /user/(?P<user_id>\d+)/.
            The action function has to accept the specified arguments as method parameters.

        named_url
            A named url that django can use to call this function. Default is controller_action

        action_name
            Set a name for the action
        
        action_prefix
            Assign a prefix for the action, applies even if
            you set action_name (template name is based on action_name, sans prefix)
    
    The prefixes will not be taken into account when determining template filenames.
    
    """
    
    def __init__(self, site, request, helper_class):
        self._site = site
        self._helper = helper_class(self)
        self._request = request
        self._response = HttpResponse()
        self._action_name = None
        self._action_name_sans_prefix = None
        self._action_func = None
        self._controller_name = get_controller_name(self.__class__)
        self._controller_name_sans_prefix = get_controller_name(self.__class__, with_prefix=False)
        self._flash_cache = None
        self._template_context = {}
        self._ignore_ajax = getattr(self, 'ignore_ajax', False)
        self._is_ajax = request.is_ajax()
            
        if hasattr(self, 'template_prefix'):
            self._template_prefix = getattr(self, 'template_prefix')
        else:
            self._template_prefix = self._controller_name_sans_prefix
            
        if hasattr(self, 'no_subdirectories'):
            self._template_string = "%(controller)s_%(action)s.html"
            self._ajax_template_string = "_%(controller)s_%(action)s.html"
        else:
            self._template_string = "%(controller)s/%(action)s.html"
            self._ajax_template_string = "%(controller)s/_%(action)s.html"
        self._actions = get_actions(self, with_prefix = True)
        self._actions_by_name = get_actions(self, with_prefix = False)

    def _get_params(self, all_params=False):
        if self._request.method == "POST":
            return self._request.POST
        else:
            return self._request.REQUEST
    _params = property(_get_params)

    def _call_action(self, action_name, *args, **kwargs):
        if self._actions.has_key(action_name):
            action_func = self._actions[action_name]
            action_func = getattr(self, action_func.func_name)
            return self._view_wrapper(action_func,*args, **kwargs)
        else:
            raise InvalidActionError(action_name)

    def _has_action(self, action_name, with_prefix = False):
        return (action_name in get_actions(action_name, with_prefix = with_prefix))
        
    def _get_action_name(self, action_func, with_prefix = True):
        if not re.match(r'^[_\-A-Z0-9]',action_func.func_name[0]) and callable(action_func):
            if hasattr(action_func, 'action_name'):
                func_name = action_func.action_name
            else:
                func_name = action_func.func_name
            if with_prefix and hasattr(action_func, 'action_prefix'):
                func_name = action_func.action_prefix + func_name
            return func_name
        raise InvalidActionError(action_func.func_name)

    def _view_wrapper(self, action_func, *args, **kwargs):
        self._action_name = self._get_action_name(action_func)
        self._action_func = action_func
        self._ignore_ajax = self._ignore_ajax or getattr(action_func, 'ignore_ajax', False)
        self._action_name_sans_prefix = self._get_action_name(action_func, with_prefix=False)
        
        if hasattr(action_func,'allowed_methods'):
            if type(action_func.allowed_methods) not in (list, tuple):
                allowed_methods = [action_func.allowed_methods.upper()]
            else:
                allowed_methods = [i.upper() for i in action_func.allowed_methods]
            if self._request.method.upper() not in allowed_methods:
                return HttpResponseNotAllowed(allowed_methods)
                
        response = self.__wrap_before_filter(action_func, *args, **kwargs)
        
        send_args = {}
                
        if type(response) is dict:
            return self.__wrap_after_filter(self.__wrapped_render, response, **send_args)
        elif type(response) in (str,unicode,SafeUnicode):
            if hasattr(action_func,'mimetype'):
                send_args['mimetype'] = action_func.mimetype
            return self.__wrap_after_filter(self.__wrapped_print, response, **send_args)
        else:
            return response

    def __wrap_before_filter(self, wrapped_func, *args, **kwargs):
        if getattr(self, '_before_filter_runonce', False) == False and getattr(self._action_func,'disable_filters', False) == False:
            self._before_filter_runonce = True

            if self._before_filter.func_code.co_argcount >= 2:
                filter_response = self._before_filter(self._request)
            else:
                filter_response = self._before_filter()
            
            if type(filter_response) is dict:
                self._template_context.update(filter_response)
            elif filter_response is not None:
                return filter_response
        
        if hasattr(self, 'do_not_pass_request'):
            return wrapped_func(*args, **kwargs)
        else:
            return wrapped_func(self._request, *args, **kwargs)
        
    def __wrap_after_filter(self, wrapped_func, *args, **kwargs):
        if getattr(self, '_after_filter_runonce', False) == False and getattr(self._action_func,'disable_filters', False) == False:
            self._after_filter_runonce = True
            if self._after_filter.func_code.co_argcount >= 2:
                filter_response = self._after_filter(self._request)
            else:
                filter_response = self._after_filter()
                
            if type(filter_response) is dict:
                self._template_context.update(filter_response)
            elif filter_response is not None:
                return filter_response
                
        return wrapped_func(*args, **kwargs)

            
    def _before_filter(self, request):
        """If overridden, runs before every action.
        
        Code example:
        {{{
            def _before_filter(self):
                if self._action_name != 'login' and not self._request.user.is_authenticated():
                    return self._redirect(action='login')
                return None
        }}}
        """
        return None
        
    def _after_filter(self, request):
        return None
    def _before_render(self, request = None):
        return None
    
    def _set_cookie(self, *args, **kwargs):
        self._response.set_cookie(*args, **kwargs)
    def _delete_cookie(self, *args, **kwargs):
        self._response.delete_cookie(*args, **kwargs)
    
    def _set_mimetype(self, mimetype, charset = None):
        if mimetype is not None:
            if charset is None:
                charset = self._response._charset
            self._response['content-type'] = "%s; charset=%s" % (mimetype, charset)
    
    def _as_json(self, data, status_code = 200, *args, **kwargs):
        """Render the returned dictionary as a JSON object."""
        import json
        if self._is_ajax and 'mimetype' not in kwargs:
            kwargs['mimetype'] = 'application/json';
        self._template_context = data
        response = self.__wrap_after_filter(json.dumps, self._template_context)
        if type(response) in (str, unicode, SafeUnicode):
            return self.__wrapped_print(response, status_code=status_code, *args, **kwargs)
        else:
            return response

    def _as_yaml(self, data, default_flow_style = True, status_code = 200, *args, **kwargs):
        """Render the returned dictionary as a YAML object."""
        import yaml
        if self._is_ajax and 'mimetype' not in kwargs:
            kwargs['mimetype'] = 'application/yaml';
        return self._print(yaml.dump(data, default_flow_style=default_flow_style), status_code=status_code, *args, **kwargs)
        
    def __wrapped_print(self, text, mimetype = 'text/plain', charset=None, status_code=200):
        """Print the returned string as plain text."""
        self._before_render()
        self._set_mimetype(mimetype, charset)

        if self._response.status_code == 200:
            self._response.status_code = status_code
            
        self._response.content = text
        return self._response        

    def _print(self, text, mimetype = 'text/plain', charset=None):
        return self.__wrap_after_filter(self.__wrapped_print, text=text, mimetype=mimetype, charset=charset)

    def _get_flash(self):
        if self._flash_cache is None:
            from django_url_framework.flash import FlashManager
            self._flash_cache = FlashManager(self._request)
        return self._flash_cache
    _flash = property(_get_flash)
    
    def __wrapped_render(self, dictionary = {}, *args, **kwargs):
        """Render the provided dictionary using the default template for the given action.
            The keyword argument 'mimetype' may be used to alter the response type.
        """
        from django.template import loader
        from django.template.context import RequestContext
        
        dictionary.update({
            'request':self._request,
            'controller_name':self._controller_name,
            'controller_actions':self._actions.keys(),
            'action_name':self._action_name,
            'controller_helper':self._helper,
            'flash': self._flash,
        })
        
        mimetype = kwargs.pop('mimetype', None)
        if mimetype:
            self._response['content-type'] = ('Content-Type', mimetype)

        if 'template_name' not in kwargs:
            if self._is_ajax and self._ignore_ajax==False:
                if hasattr(self._action_func, 'ajax_template_name'):
                    template_name = self._action_func.ajax_template_name
                else:
                    template_name = self._ajax_template_string % {'controller':self._template_prefix, 'action':self._action_name}
            elif hasattr(self._action_func,'template_name'):
                template_name = self._action_func.template_name
            else:
                template_name = self._template_string % {'controller':self._template_prefix, 'action':self._action_name}
            kwargs['template_name'] = template_name
            
        if 'context_instance' not in kwargs:
            kwargs['context_instance'] = RequestContext(self._request)

        self._template_context.update(dictionary)
        
        if getattr(self, '_before_render_runonce', False) == False and getattr(self._action_func,'disable_filters', False) == False:
            self._before_render_runonce = True
            before_render_response = self._before_render()
            if type(before_render_response) is dict:
                self._template_context.update(before_render_response)
            elif before_render_response is not None:
                return before_render_response

        obj = getattr(self, '_object',None)
        if obj is not None:
            populate_xheaders(self._request, self._response, obj.__class__, obj.pk)

        self._response.content = loader.render_to_string(dictionary=self._template_context, *args, **kwargs)
        return self._response
    
    _render = __wrapped_render
    
    def __wrapped_redirect(self, to_url, *args, **kwargs):
        if to_url is None:
            to_url = self._helper.url_for(*args, **kwargs)
        return HttpResponseRedirect(to_url)
    def __wrapped_permanent_redirect(self, to_url, *args, **kwargs):
        if to_url is None:
            to_url = self._helper.url_for(*args, **kwargs)
        return HttpResponsePermanentRedirect(to_url)
    
    def _redirect(self, to_url = None, *args, **kwargs):
        return self.__wrap_after_filter(self.__wrapped_redirect, to_url, *args, **kwargs)
    _go = _redirect
    
    def _permanent_redirect(self, to_url, *args, **kwargs):
        return self.__wrap_after_filter(self.__wrapped_permanent_redirect, to_url, *args, **kwargs)
        