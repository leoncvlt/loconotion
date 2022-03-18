FROM python:3.8

# ChromeDriver installation from https://gist.github.com/varyonic/dea40abcf3dd891d204ef235c6e8dd79
# We need wget to set up the PPA and xvfb to have a virtual screen and unzip to install the Chromedriver
RUN apt-get update
RUN apt-get install -y libgconf-2-4 wget xvfb unzip

# Install Chrome (compatible version with chromedriver below)
ARG CHROME_VERSION="99.0.4844.74-1"
RUN wget --no-verbose -O /tmp/chrome.deb https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${CHROME_VERSION}_amd64.deb \
  && apt install -y /tmp/chrome.deb \
  && rm /tmp/chrome.deb

# RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
# RUN dpkg -i google-chrome-stable_current_amd64.deb; apt-get -fy install
# Set up Chromedriver Environment variables
ENV CHROMEDRIVER_VERSION 99.0.4844.51
ENV CHROMEDRIVER_DIR /chromedriver
RUN mkdir $CHROMEDRIVER_DIR
# Download and install Chromedriver
RUN wget -q --continue -P $CHROMEDRIVER_DIR "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip"
RUN unzip $CHROMEDRIVER_DIR/chromedriver* -d $CHROMEDRIVER_DIR
# Put Chromedriver into the PATH
ENV PATH $CHROMEDRIVER_DIR:$PATH

RUN mkdir -p /app/loconotion/
WORKDIR /app/loconotion/
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
ENTRYPOINT [ "python", "loconotion", "--chromedriver", "/chromedriver/chromedriver"]
