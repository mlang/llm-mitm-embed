install:
	pipx install mitmproxy
	pipx inject mitmproxy python-frontmatter
	ln -s $(shell pwd)/llm-mitm-embed.service $(HOME)/.config/systemd/user/
	systemctl --user daemon-reload
