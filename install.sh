echo "System package updating..."
sudo apt-get update
sudo apt-get upgrade

echo "Installing Teamviewer..."
wget https://download.teamviewer.com/download/linux/teamviewer-host_armhf.deb
sudo dpkg -i teamviewer-host_armhf.deb
sudo apt --fix-broken install
sudo teamviewer passwd <password>
teamviewer info

echo "Installing Git..."
sudo apt-get install git

echo "Installing Pyenv..."
curl https://pyenv.run | bash
echo 'export PATH="$HOME/.pyenv/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
sudo apt-get install -y make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev python-openssl

echo "Initial Pyenv..."
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

echo "Installing Python..."
pyenv install 3.7.4
pyenv global 3.7.4

echo "Installing Pipenv..."
pip install pipenv

echo "Cloning source..."
git clone https://github.com/cjltsod/bookcloud_client.git

echo "Linking splash image..."
sudo rm /usr/share/plymouth/themes/pix/splash.png
sudo ln -s /home/pi/bookcloud_client/assets/splash.png /usr/share/plymouth/themes/pix/splash.png

echo "Generating autosart..."
echo '@lxpanel --profile LXDE-pi' >> ~/.config/lxsession/LXDE-pi/autostart
echo '@pcmanfm --desktop --profile LXDE-pi' >> ~/.config/lxsession/LXDE-pi/autostart
echo '@lxterminal -l --geometry=1x1 --title=BookCloudClient --working-directory=/home/pi/bookcloud_client -e /home/pi/bookcloud_client/boot.sh' >> ~/.config/lxsession/LXDE-pi/autostart
echo '@xscreensaver -no-splash' >> ~/.config/lxsession/LXDE-pi/autostart
echo 'point-rpi' >> ~/.config/lxsession/LXDE-pi/autostart
chmod u+x ~/bookcloud_client/boot.sh
