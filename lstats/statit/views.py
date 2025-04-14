import asyncio
import json
from collections import defaultdict
from hashlib import sha256
from html.parser import HTMLParser

from django.shortcuts import render
from django.views import View
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse_lazy, reverse
from django.http.request import HttpRequest
from django.http.response import HttpResponse, JsonResponse, HttpResponseRedirect

from asgiref.sync import sync_to_async
from aiohttp.client import ClientSession

from .models import UserLinks
# Create your views here.

class AsyncLoginRequiredMixin(AccessMixin):
    login_url = reverse_lazy('login')

    async def dispatch(self, request, *args, **kwargs):
        user = await request.auser()
        if not user.is_authenticated:
            return await self.handle_no_permission()
        return await super().dispatch(request, *args, **kwargs)

    async def handle_no_permission(self):
        return redirect_to_login(
            self.request.get_full_path(),
            self.get_login_url(),
            self.get_redirect_field_name()
        )


class AsyncUserPassesTestMixin(AccessMixin):
    async def dispatch(self, request, *args, **kwargs):
        user = await request.auser()
        if not await self.test_func(user):
            return await self.handle_no_permission()
        return await super().dispatch(request, *args, **kwargs)

    async def handle_no_permission(self):
        return redirect_to_login(self.request.get_full_path(), self.get_login_url(), self.get_redirect_field_name())

    async def test_func(self, user):
        """
        Override as needed in individual CBVs
        """
        return user.is_active

class LinkStatParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.link_stats = defaultdict(int)

    def handle_starttag(self, tag, attrs):
        self.link_stats[tag] += 1

    def handle_startendtag(self, tag, attrs):
        self.link_stats[tag] += 1

    def get_stats(self) -> dict:
        return self.link_stats

async def get_link_stats(link: str) -> dict:
    res = {'link': link, 'stats': '{}'}
    print(f'{link}')
    async with ClientSession(trust_env=True) as session:
        async with session.get(link) as response:
            print(f'{link}: {response.status}')
            res['status'] = response.status
            res['content_type'] = response.content_type
            if response.status < 300:
                if response.content_type == 'application/json':
                    r_dict = await response.json()
                    s_dict = dict(zip(r_dict.keys(), ([1]*len(r_dict.keys()))))
                    res['stats'] = json.dumps(s_dict)
                elif 'html' in response.content_type:
                    lp = LinkStatParser()
                    s_text = await response.text()
                    lp.feed(s_text)
                    lp.close()
                    s_dict = lp.get_stats()
                    res['stats'] = json.dumps(s_dict)
                else:
                    res['stats'] = {'error': 'This content type has no stats'}

    return res

class LinksView(AsyncLoginRequiredMixin, AsyncUserPassesTestMixin, View):
    async def get(self, request: HttpRequest) -> HttpResponse:
        user = await request.auser()
        links = await sync_to_async(UserLinks.objects.filter)(fk_user=user)

        links_list = []
        tasks = [get_link_stats(l.link) async for l in links]

        results = await asyncio.gather(*tasks)

        for l in results:
        # for l in links:
            l_stats = json.loads(l['stats'] if l['stats'] else '{}')
            l_dict  = {'link_': l['link'], 'status_': l['status'],
                       'content_type_': l['content_type'], 'stats': l_stats}

            links_list.append(l_dict)

        return await sync_to_async(render)(request,
                                           'home.html',
                                           {'links_list': links_list})

    async def post(self, request: HttpRequest) -> HttpResponse:
        user = await request.auser()
        if request.content_type == 'application/x-www-form-urlencoded':
            new_link = request.POST.get('link')
            sha_hash = sha256(new_link.encode()).hexdigest()

            e_count = await UserLinks.objects.filter(fk_user=user, link_hash=sha_hash).acount()
            if e_count:
                return HttpResponseRedirect(redirect_to=reverse('home'))

            nu_link = UserLinks()
            nu_link.link=new_link
            nu_link.link_hash = sha_hash
            nu_link.fk_user=user
            await nu_link.asave()

            return HttpResponseRedirect(redirect_to=reverse('home'))

        link_struct = json.loads(request.body)

        if 'id' in link_struct:
            # this is an update of existing item
            if 'link' in link_struct and link_struct['link']:
                sh = sha256()
                sh.update(link_struct['link'])
                t_link_hash = sh.hexdigest()

                try:
                    target_link: UserLinks = UserLinks.objects.get(fk_user=user, pk=link_struct['id'])
                    target_link.link = link_struct['link']
                    target_link.stats = '{}'
                    target_link.status = 0
                    target_link.content_type = ''

                    target_link.link_hash = t_link_hash

                    await target_link.asave()
                    return HttpResponseRedirect(redirect_to=reverse('home'))
                except Exception as ex:
                    return HttpResponse(content=repr(ex).encode())


