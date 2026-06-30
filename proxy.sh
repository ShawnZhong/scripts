export http_proxy=http://squid.cs.wisc.edu:3128
export https_proxy=$http_proxy
export ftp_proxy=$http_proxy

echo 'Acquire::http::Proxy "http://squid.cs.wisc.edu:3128";' | sudo tee /etc/apt/apt.conf
echo 'Acquire::https::Proxy "http://squid.cs.wisc.edu:3128";' | sudo tee /etc/apt/apt.conf

git config --global http.proxy http://squid.cs.wisc.edu:3128
git config --global https.proxy http://squid.cs.wisc.edu:3128

git config --global --unset https.proxy
git config --global --unset http.proxy
