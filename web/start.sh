#!/bin/bash

uwsgi --http 0.0.0.0:800 --master -p 4 -w app:app