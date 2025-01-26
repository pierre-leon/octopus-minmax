# Octopus Minmax Bot 🐙🤖

## Description
This bot will use your electricity usage and compare your current Smart tariff costs for the day with another smart tariff and initiate a switch if it's cheaper. Currently it switches only between Octopus Agile and Octopus Go.

Due to how Octopus Energy's Smart tariffs work, switching manually makes the *new* tariff take effect from the start of the day e.g. if you switch at 11PM then the whole costs for that day will be re-calculated based on your new tariff, allowing you to potentially save money by tariff-hopping. 

I created this because I've been a long time Agile customer who got tired of the price spikes. I now use this to enjoy the benefits of Agile (cheap days) without the risks (expensive days). 

I personally have this running automatically evey day at 11PM inside a Raspberry Pi docker container, but you can run it wherever you want. It also uses discord webhooks to send you updates and logs, but that's not necessary to work.

## How to use
**Note**: This requires your email/password when using Playwright to log into your account. None of your data goes anywhere except to Octopus Energy.
#### Requirements
- An Octopus Energy Account 
  - In case you don't have one, we both get £50 for using my referral https://share.octopus.energy/coral-lake-50
- Have a smart meter
- Be on Octopus Agile or Octopus Go (Can add more options in the future)
- Have an Octopus Home Mini for real-time usage (**Important**)

#### Steps
1. Install the Python requirements
2. Fill out `config.py` with your api key and stuff
3. Schedule this to run once a day with a CRON job or something. I recommend at 11PM to leave yourself an hour as a safety margin in case Octopus takes a while to generate your new agreement.
