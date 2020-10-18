FROM python:3.8

# ChromeDriver installation from https://gist.github.com/varyonic/dea40abcf3dd891d204ef235c6e8dd79
# We need wget to set up the PPA and xvfb to have a virtual screen and unzip to install the Chromedriver
RUN apt-get update
RUN apt-get install -y libgconf-2-4 wget xvfb unzip
# Set up the Chrome PPA
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add -
RUN echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list
# Update the package list and install chrome
RUN apt-get update -y
RUN apt-get install -y google-chrome-stable

# RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
# RUN dpkg -i google-chrome-stable_current_amd64.deb; apt-get -fy install
# Set up Chromedriver Environment variables
ENV CHROMEDRIVER_VERSION 85.0.4183.38
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
