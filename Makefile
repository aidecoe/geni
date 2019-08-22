.PHONY: clean release

clean:
	-$(RM) -r -v build dist geni.egg-info
	-find geni -name __pycache__ -type d -printf "removed '%p'\n" -exec rm -r '{}' +

release:
	python setup.py bdist_wheel
