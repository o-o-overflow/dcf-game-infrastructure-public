# Prerequisites

Install the deps
```bash
$ pip install -r reqs.txt
```

## AWS Configuration

In order to deploy to the public AWS buckets, you will need a profile named `ooo` in
your `~/.aws/credentials` file containing your `aws_access_key_id` and
`aws_secret_access_key`. For more information on setting up this file see:
https://docs.aws.amazon.com/sdk-for-java/v1/developer-guide/setup-credentials.html

# How to use

Clone all the challs, load them, and get `Challenge` objects with all the info.  This will result in a service_info.yml file that can be used to update the database.
```bash
$ ./challenge_loader.py loadall [.challs file path]
```

To prepare the file necessary for updating all the challenges on the scoreboard
run (run `./challenge loadall` first):

```bash
$ ./challenge_loader.py scoreboard
```

To test the loading steps locally (so that you can test this stuff before bothering odo/hacopo/bryce):
```bash
add to the list of challs
$ ./challenge_loader.py test_chall (name)
```

# Notes about where to store the flag

Typically, the flag is stored at flag_path, which is the location refreshed by gamebot.

# Notes about storing pointers to challs repos

For now I opted to avoid using git submodules. Having a file with the list of
challs seems more flexbile, and we don't need to mess around with different set
of submodules if we want to load different sets of challs (in the current
version, it's just one file with the list of names, seemed much easier to me).
