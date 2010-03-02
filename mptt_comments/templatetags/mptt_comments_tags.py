from django.contrib.comments.templatetags.comments import BaseCommentNode, CommentListNode
from django import template
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
import mptt_comments

register = template.Library()

class BaseMpttCommentNode(BaseCommentNode):
    
    root_node = None
    
    def __init__(self, ctype=None, object_pk_expr=None, object_expr=None, as_varname=None, root_only=False, with_parent=None, reverse=False, comment=None):
        super(BaseMpttCommentNode, self). __init__(ctype=ctype, object_pk_expr=object_pk_expr, object_expr=object_expr, as_varname=as_varname, comment=comment)
        self.comment_model = mptt_comments.get_model()
        self.with_parent = with_parent
        self.root_only = root_only
        self.reverse = reverse
    
    def get_root_node(self, context):
        if not self.root_node:
            ctype, object_pk = self.get_target_ctype_pk(context)
            self.root_node = self.comment_model.objects.get_root_comment(ctype, object_pk)
        return self.root_node
        
    def handle_token(cls, parser, token):
        """
            Class method to parse get_comment_list/count/form and return a Node.

            Forked from django.contrib.comments.templatetags. with_parent, 
            root-only concepts borrowed from django-threadedcomments.
        """
        tokens = token.contents.split()
        
        with_parent = None
        extra_kw = {}
        extra_possible_kw = ('root_only', 'reverse')
        for dummy in extra_possible_kw:
            if tokens[-1] in extra_possible_kw:
                extra_kw[str(tokens.pop())] = True

        if tokens[1] != 'for':
            raise template.TemplateSyntaxError("Second argument in %r tag must be 'for'" % tokens[0])

        # {% get_whatever for obj as varname %}
        # {% get_whatever for obj as varname with parent %}
        if len(tokens) == 5 or len(tokens) == 7:
            if tokens[3] != 'as':
                raise template.TemplateSyntaxError("Third argument in %r must be 'as'" % tokens[0])
            if len(tokens) == 7:
                if tokens[5] != 'with':
                    raise template.TemplateSyntaxError("When 6 arguments are given, fifth argument in %r must be 'with' followed by the parent commment wanted" % tokens[0])
                with_parent = tokens[6]
            return cls(
                object_expr = parser.compile_filter(tokens[2]),
                as_varname = tokens[4],
                with_parent = with_parent,
                **extra_kw
            )

        # {% get_whatever for app.model pk as varname %}
        # {% get_whatever for app.model pk as varname with parent %}
        elif len(tokens) == 6 or len(tokens) == 8:
            if tokens[4] != 'as':
                raise template.TemplateSyntaxError("Fourth argument in %r must be 'as'" % tokens[0])
            if len(tokens) == 8:
                if tokens[6] != 'with':
                    raise template.TemplateSyntaxError("When 6 arguments are given, fifth argument in %r must be 'with' followed by the parent commment wanted" % tokens[0])
                with_parent = tokens[7]
            return cls(
                ctype = BaseCommentNode.lookup_content_type(tokens[2], tokens[0]),
                object_pk_expr = parser.compile_filter(tokens[3]),
                as_varname = tokens[5],
                with_parent = with_parent,
                **extra_kw
            )

        else:
            raise template.TemplateSyntaxError("%r tag requires 4, 5, 6 or 7 arguments" % tokens[0])

    handle_token = classmethod(handle_token)
        
class MpttCommentFormNode(BaseMpttCommentNode):
    """Insert a form for the comment model into the context."""
            
    def get_form(self, context):
        ctype, object_pk = self.get_target_ctype_pk(context)
        if object_pk:
            return mptt_comments.get_form()(ctype.get_object_for_this_type(pk=object_pk), parent_comment=self.get_root_node(context))
        else:
            return None

    def render(self, context):
        context[self.as_varname] = self.get_form(context)
        return ''

class MpttCommentListNode(BaseMpttCommentNode):

    offset = getattr(settings, 'MPTT_COMMENTS_OFFSET', 20)
    toplevel_offset = getattr(settings, 'MPTT_COMMENTS_TOPLEVEL_OFFSET', 20)
    cutoff_level = getattr(settings, 'MPTT_COMMENTS_CUTOFF', 3)
    bottom_level = 0 
    
    def get_query_set(self, context):
        qs = super(MpttCommentListNode, self).get_query_set(context)
        root_node = self.get_root_node(context)
        cutoff = self.cutoff_level
        
        if self.with_parent:
            if self.with_parent in context:
                parent = context[self.with_parent]
                qs = qs.filter(lft__gt=parent.lft, rght__lt=parent.rght)
                self.bottom_level = parent.level
            else:
               raise template.TemplateSyntaxError("Variable %s doesn't exist in context" % self.with_parent)
        if self.root_only:
            cutoff = 1

        return qs.filter(tree_id=root_node.tree_id, level__gte=1, level__lte=cutoff)
        
    def get_context_value_from_queryset(self, context, qs):
        if self.reverse:
            qs = qs.reverse()
        return list(qs[:self.get_offset()])
        
    def get_offset(self):
        if self.root_only:
            return self.toplevel_offset
        else:
            return self.offset
        
    def render(self, context):
        qs = self.get_query_set(context)
        context[self.as_varname] = self.get_context_value_from_queryset(context, qs)
        comments_remaining = qs.count()
        context['comments_remaining'] = (comments_remaining - self.get_offset()) > 0 and comments_remaining - self.get_offset() or 0
        context['root_comment'] = self.get_root_node(context)
        context['collapse_levels_above'] = getattr(settings, 'MPTT_COMMENTS_COLLAPSE_ABOVE', 2)
        context['cutoff_level'] = self.cutoff_level
        context['bottom_level'] = self.bottom_level
        return ''        
        
def get_mptt_comment_list(parser, token):
    """
    Gets the list of comments for the given params and populates the template
    context with a variable containing that value, whose name is defined by the
    'as' clause.

    Syntax::

        {% get_comment_list for [object] as [varname]  %}
        {% get_comment_list for [app].[model] [object_id] as [varname]  %}

    Example usage::

        {% get_comment_list for event as comment_list %}
        {% for comment in comment_list %}
            ...
        {% endfor %}

    """
    return MpttCommentListNode.handle_token(parser, token)


def get_mptt_comment_form(parser, token):
    """
    Get a (new) form object to post a new comment.

    Syntax::

        {% get_comment_form for [object] as [varname] %}
        {% get_comment_form for [app].[model] [object_id] as [varname] %}
    """
    return MpttCommentFormNode.handle_token(parser, token)


def mptt_comment_form_target():
    """
    Get the target URL for the comment form.

    Example::

        <form action="{% comment_form_target %}" method="POST">
    """
    return mptt_comments.get_form_target()

def children_count(comment):
    return (comment.rght - comment.lft) / 2

def mptt_comments_media():

    return mark_safe( render_to_string( ('comments/comments_media.html',) , { }) )
    
def mptt_comments_media_css():

    return mark_safe( render_to_string( ('comments/comments_media_css.html',) , { }) )
    
def mptt_comments_media_js():

    return mark_safe( render_to_string( ('comments/comments_media_js.html',) , { }) )
    
def display_comment_toplevel_for(target):

    model = target.__class__
        
    template_list = [
        "comments/%s_%s_display_comments_toplevel.html" % tuple(str(model._meta).split(".")),
        "comments/%s_display_comments_toplevel.html" % model._meta.app_label,
        "comments/display_comments_toplevel.html"
    ]
    return render_to_string(
        template_list, {
            "object" : target
        } 
        # RequestContext(context['request'], {})
    )
    
register.filter(children_count)
register.tag(get_mptt_comment_form)
register.simple_tag(mptt_comment_form_target)
register.simple_tag(mptt_comments_media)
register.simple_tag(mptt_comments_media_css)
register.simple_tag(mptt_comments_media_js)
register.tag(get_mptt_comment_list)
register.simple_tag(display_comment_toplevel_for)
