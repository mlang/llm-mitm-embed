"""A mitmproxy script to embed visited content."""

import json
import subprocess
import threading
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen, Request

from flask import Flask, request, make_response
import frontmatter
from mitmproxy import ctx
from mitmproxy.addons.asgiapp import WSGIApp


USER_AGENT = 'MyClientSoftware/1.0'


class EmbedVisited:
    def load(self, loader):
        loader.add_option(
            name='llm_embed_model',
            typespec=str,
            default='3-large',
            help="LLM embedding model"
        )
        loader.add_option(
            name='llm_embed_collection',
            typespec=str,
            default='visited',
            help="Collection to store embeddings in"
        )


    def response(self, flow):
        if flow.request.host.endswith('.local'): return
        if flow.request.host in ('localhost', '127.0.0.1'): return
        if flow.request.method != "GET": return
        if flow.response.status_code != 200: return

        threading.Thread(target=embed, args=(flow.request.url,)).start()


search = Flask('embeddings-search')

@search.route('/')
def search_form() -> str:
    return """
        <html>
        <body>
            <form action="/search" method="post">
                <input type="text" name="q" placeholder="Search..." />
                <input type="submit" value="Search" />
            </form>
        </body>
        </html>
    """

cache = dict()

@search.route('/search', methods=['POST'])
def search_result():
    q = request.form.get('q')
    process = subprocess.run(
        ['llm', 'similar', '-c', q, ctx.options.llm_embed_collection],
        stdout=subprocess.PIPE, text=True
    )
    results = [json.loads(rec) for rec in process.stdout.split("\n") if rec]
    ul = '<ol>'
    for item in results:
        if item['metadata']:
            post = frontmatter.Post(item['content'],
                handler=frontmatter.YAMLHandler(), **item['metadata']
            )
            cache[item['id']] = frontmatter.dumps(post)
        else:
            cache[item['id']] = item['content']

        score = round(item['score'], 3)
        url = item['id']
        title = item['metadata']['title'] if item['metadata'] else None
        synopsis = "<br>"
        if item['metadata']:
            if "description" in item['metadata']:
                synopsis = f'<p>{item["metadata"]["description"]}</p>'
        ul += f'<li>{score}: <a href="{url}">{title or url}</a>'
        ul += f'{synopsis}<form action="/cache" method="POST">'
        ul += f'<input type="hidden" name="id" value="{item["id"]}">'
        ul += '<input type="submit" value="Cached">'
        ul += '</form></li>'
    ul += '</ol>'

    return f"""
        <html>
        <body>
            <h1>Search Results for: {q}</h1>
            {ul}
        </body>
        </html>
    """


@search.route('/cache', methods=['POST'])
def cached_content():
    response = make_response(cache[request.form.get('id')])
    response.mimetype = 'text/plain'
    return response


addons = [EmbedVisited(), WSGIApp(search, ctx.options.listen_host, ctx.options.listen_port)]


#------------------------------------------------------------------------------#


def embed(url: str) -> None:
    metadata, content = markdown(url)
    llm = ['llm', 'embed',
        '--model', ctx.options.llm_embed_model,
        '--input', '-',
        '--store',
        *(['--metadata', json.dumps(metadata, default=str)] if metadata else []),
        ctx.options.llm_embed_collection, url
    ]
    subprocess.run(llm, input=content, text=True)


def markdown(url):
    parsed = urlparse(url)
    pure = urlunparse((
        parsed.scheme, "pure.md", f'/{parsed.netloc}{parsed.path}',
        parsed.params, parsed.query, ''
    ))
    request = Request(pure, headers={'User-Agent': USER_AGENT})
    with urlopen(request) as response:
        content = response.read().decode('utf-8')
        try:
            return frontmatter.parse(content,
                handler=frontmatter.YAMLHandler()
            )
        except Exception as e:
            print(content)
            print(e)
            return {}, content
