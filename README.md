## installing
The trickiest thing is installing geopandas. You'll need GDAL + Fiona before that works, get those binaries [here](https://www.lfd.uci.edu/~gohlke/pythonlibs/#fiona) and [here](https://www.lfd.uci.edu/~gohlke/pythonlibs/#gdal). The order of operations for install is GDAL, Fiona, then geopandas.

In order to run the pipeline notebooks, you'll also need to copy the config-example.json file, renaming it config.json. If you want to point it at the full-sized Wikipedia XML dump, this is where you do it. 

Fiona @ file:///C:/Users/rowan/Downloads/Fiona-1.8.13-cp37-cp37m-win_amd64.whl
GDAL @ file:///C:/Users/rowan/Downloads/GDAL-3.0.4-cp37-cp37m-win_amd64.whl
geopandas @ file:///C:/Users/rowan/Downloads/geopandas-0.7.0-py3-none-any.whl
pandas==1.0.3
Shapely==1.7.0
