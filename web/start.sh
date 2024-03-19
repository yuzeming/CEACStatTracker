#!/bin/bash

uwsgi --http 0.0.0.0:80 --master -p 4 -w app:app