from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect, HttpResponseNotAllowed
from django.shortcuts import render_to_response, get_object_or_404, redirect
from django.template import RequestContext
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from geonode.layers.models import Layer 
from geonode.maps.models import Map
from geonode.search.normalizers import apply_normalizers
from geonode.contrib.groups.forms import GroupInviteForm, GroupForm, GroupUpdateForm, GroupMemberForm
from geonode.contrib.groups.models import Group, GroupInvitation, GroupMember
from django.views.generic import ListView


def group_list(request, template='groups/group_list.html'):
    from geonode.search.views import search_page
    post = request.POST.copy()
    post.update({'type': 'group'})
    request.POST = post
    return search_page(request, template=template)

@login_required
def group_create(request):
    if request.method == "POST":
        form = GroupForm(request.POST, request.FILES)
        if form.is_valid():
            group = form.save(commit=False)
            group.save()
            form.save_m2m()
            group.join(request.user, role="manager")
            return HttpResponseRedirect(reverse("group_detail", args=[group.slug]))
    else:
        form = GroupForm()
    
    return render_to_response("groups/group_create.html", {
        "form": form,
    }, context_instance=RequestContext(request))


@login_required
def group_update(request, slug):
    group = Group.objects.get(slug=slug)
    if not group.user_is_role(request.user, role="manager"):
        return HttpResponseForbidden()
    
    if request.method == "POST":
        form = GroupUpdateForm(request.POST, request.FILES, instance=group)
        if form.is_valid():
            group = form.save(commit=False)
            group.save()
            form.save_m2m()
            return HttpResponseRedirect(reverse("group_detail", args=[group.slug]))
    else:
        form = GroupForm(instance=group)
    
    return render_to_response("groups/group_update.html", {
        "form": form,
        "group": group,
    }, context_instance=RequestContext(request))


class GroupDetailView(ListView):
    """
    Mixes a detail view (the group) with a ListView (the members).
    """

    model = User
    template_name = "groups/group_detail.html"
    paginate_by = None
    group = None

    def get_queryset(self):
        return self.group.member_queryset()

    def get(self, request, *args, **kwargs):
        self.group = get_object_or_404(Group, slug=kwargs.get('slug'))
        return super(GroupDetailView, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(GroupDetailView, self).get_context_data(**kwargs)
        context['object'] = self.group
        context['maps'] = self.group.resources(resource_type=Map)
        context['layers'] = self.group.resources(resource_type=Layer)
        context['is_member'] = self.group.user_is_member(self.request.user)
        context['is_manager'] = self.group.user_is_role(self.request.user, "manager")
        context['object_list'] = apply_normalizers({'users': [obj.user.profile for obj in context['object_list']]})
        context['total'] = self.get_queryset().count()
        return context


def group_detail(request, slug):
    group = get_object_or_404(Group, slug=slug)
    
    if not group.can_view(request.user):
        raise Http404()
        
    maps = group.resources(resource_type=Map)
    layers = group.resources(resource_type=Layer)
    
    ctx = {
        "object": group,
        "maps": maps,
        "layers": layers,
        "object_list": group.member_queryset(),
        "is_member": group.user_is_member(request.user),
        "is_manager": group.user_is_role(request.user, "manager"),
    }
    ctx = RequestContext(request, ctx)
    return render_to_response("groups/group_detail.html", ctx)


def group_members(request, slug):
    group = get_object_or_404(Group, slug=slug)
    ctx = {}
    
    if not group.can_view(request.user):
        raise Http404()
    
    if group.access in ["public-invite", "private"] and group.user_is_role(request.user, "manager"):
        ctx["invite_form"] = GroupInviteForm()

    if group.user_is_role(request.user, "manager"):
        ctx["member_form"] = GroupMemberForm()
    
    ctx.update({
        "object": group,
        "members": group.member_queryset(),
        "is_member": group.user_is_member(request.user),
        "is_manager": group.user_is_role(request.user, "manager"),
    })
    ctx = RequestContext(request, ctx)
    return render_to_response("groups/group_members.html", ctx)

@require_POST
@login_required
def group_members_add(request, slug):
    group = get_object_or_404(Group, slug=slug)
    
    if not group.user_is_role(request.user, role="manager"): 
        return HttpResponseForbidden()
    
    form = GroupMemberForm(request.POST)
    
    if form.is_valid():
        role = form.cleaned_data["role"]
        for user in form.cleaned_data["user_identifiers"]:
            # dont add them if already a member, just update the role
            try:
                gm = GroupMember.objects.get(user=user, group=group)
                gm.role = role
                gm.save()
            except:
                gm = GroupMember(user=user, group=group, role=role)
                gm.save()
    return redirect("group_detail", slug=group.slug)


@login_required
def group_member_remove(request, slug, username):
    group = get_object_or_404(Group, slug=slug)
    user = get_object_or_404(User, username=username)
    
    if not group.user_is_role(request.user, role="manager"):
        return HttpResponseForbidden()
    else:
        GroupMember.objects.get(group=group, user=user).delete()
        return redirect("group_detail", slug=group.slug)
        
@require_POST
@login_required
def group_join(request, slug):
    group = get_object_or_404(Group, slug=slug)
    
    if group.access == "private":
        raise Http404()
    
    if group.user_is_member(request.user):
        return redirect("group_detail", slug=group.slug)
    else:
        group.join(request.user, role="member")
        return redirect("group_detail", slug=group.slug)


@require_POST
def group_invite(request, slug):
    group = get_object_or_404(Group, slug=slug)
    
    if not group.can_invite(request.user):
        raise Http404()
    
    form = GroupInviteForm(request.POST)
    
    if form.is_valid():
        for user in form.cleaned_data["invite_user_identifiers"].split("\n"):
            group.invite(user, request.user, role=form.cleaned_data["invite_role"])
    
    return redirect("group_members", slug=group.slug)


@login_required
def group_invite_response(request, token):
    invite = get_object_or_404(GroupInvitation, token=token)
    ctx = {"invite": invite}
    
    if request.user != invite.user:
        redirect("group_detail", slug=invite.group.slug)
    
    if request.method == "POST":
        if "accept" in request.POST:
            invite.accept(request.user)
        
        if "decline" in request.POST:
            invite.decline()
        
        return redirect("group_detail", slug=invite.group.slug)
    else:
        ctx = RequestContext(request, ctx)
        return render_to_response("groups/group_invite_response.html", ctx)


@login_required
def group_remove(request, slug):
    group = get_object_or_404(Group, slug=slug)
    if request.method == 'GET':
        return render_to_response("groups/group_remove.html", RequestContext(request, {
            "group": group
        }))
    if request.method == 'POST':

        if not group.user_is_role(request.user, role="manager"):
            return HttpResponseForbidden()

        group.delete()
        return HttpResponseRedirect(reverse("group_list"))
    else:
        return HttpResponseNotAllowed()
