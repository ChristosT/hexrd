import lmfit
import numpy as np

from hexrd.instrument import switch_xray_source

from .lmfit_param_handling import (
    add_engineering_constraints,
    create_instr_params,
    create_tth_parameters,
    DEFAULT_EULER_CONVENTION,
    tth_parameter_prefixes,
    update_instrument_from_params,
)


class StructurelessCalibrator:
    """
    this class implements the equivalent of the
    powder calibrator but without constraining
    the optimization to a structure. in this
    implementation, the location of the constant
    two theta line that a set of points lie on
    is also an optimization parameter.

    unlike the previous implementations, this routine
    is based on the lmfit module to implement the
    more complicated constraints for the TARDIS box

    if TARDIS_constraints are set to True, then the following
    additional linear constraint is added to the calibration

    22.83 mm <= |IMAGE-PLATE-2 tvec[1]| + |IMAGE-PLATE-2 tvec[1]| <= 23.43 mm

    """
    def __init__(self,
                 instr,
                 data,
                 tth_distortion=None,
                 engineering_constraints=None,
                 euler_convention=DEFAULT_EULER_CONVENTION):

        self._instr = instr
        self._data = data
        self._tth_distortion = tth_distortion
        self._engineering_constraints = engineering_constraints
        self.euler_convention = euler_convention
        self.make_lmfit_params()
        self.set_minimizer()

    def make_lmfit_params(self):
        params = []
        params += create_instr_params(self.instr, self.euler_convention)
        params += create_tth_parameters(self.instr, self.meas_angles)

        params_dict = lmfit.Parameters()
        params_dict.add_many(*params)

        add_engineering_constraints(params_dict, self.engineering_constraints)
        self.params = params_dict
        return params_dict

    def calc_residual(self, params):
        update_instrument_from_params(
            self.instr,
            params,
            self.euler_convention,
        )

        # Store these in variables so they are only computed once.
        meas_angles = self.meas_angles
        tth_correction = self.tth_correction

        residual = []
        prefixes = tth_parameter_prefixes(self.instr)
        for xray_source in self.data:
            prefix = prefixes[xray_source]
            for ii, (rng, corr_rng) in enumerate(zip(
                meas_angles[xray_source],
                tth_correction[xray_source]
            )):
                for det_name, panel in self.instr.detectors.items():
                    if rng[det_name] is None or rng[det_name].size == 0:
                        continue

                    tth_rng = params[f'{prefix}{ii}'].value
                    tth_updated = np.degrees(rng[det_name][:, 0])
                    delta_tth = tth_updated - tth_rng
                    if corr_rng[det_name] is not None:
                        delta_tth -= np.degrees(corr_rng[det_name])
                    residual.append(delta_tth)

        return np.hstack(residual)

    def set_minimizer(self):
        self.fitter = lmfit.Minimizer(self.calc_residual,
                                      self.params,
                                      nan_policy='omit')

    def run_calibration(self,
                        method='least_squares',
                        odict=None):
        """
        odict is the options dictionary
        """
        if odict is None:
            odict = {}

        if method == 'least_squares':
            fdict = {
                "ftol": 1e-8,
                "xtol": 1e-8,
                "gtol": 1e-8,
                "verbose": 2,
                "max_nfev": 1000,
                "x_scale": "jac",
                "method": "trf",
                "jac": "3-point",
            }
            fdict.update(odict)

            self.res = self.fitter.least_squares(self.params,
                                                 **fdict)
        else:
            fdict = odict
            self.res = self.fitter.scalar_minimize(method=method,
                                                   params=self.params,
                                                   max_nfev=50000,
                                                   **fdict)

        self.params = self.res.params
        # res = self.fitter.least_squares(**fdict)
        return self.res

    @property
    def tth_distortion(self):
        return self._tth_distortion

    @tth_distortion.setter
    def tth_distortion(self, v):
        self._tth_distortion = v
        # No need to update lmfit parameters

    @property
    def engineering_constraints(self):
        return self._engineering_constraints

    @engineering_constraints.setter
    def engineering_constraints(self, v):
        if v == self._engineering_constraints:
            return

        valid_settings = [
            None,
            'None',
            'TARDIS',
        ]
        if v not in valid_settings:
            valid_str = ', '.join(map(valid_settings, str))
            msg = (
                f'Invalid engineering constraint "{v}". Valid constraints '
                f'are: "{valid_str}"'
            )
            raise Exception(msg)

        self._engineering_constraints = v
        self.make_lmfit_params()

    @property
    def instr(self):
        return self._instr

    @instr.setter
    def instr(self, ins):
        self._instr = ins
        self.make_lmfit_params()

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, dat):
        self._data = dat
        self.make_lmfit_params()

    @property
    def residual(self):
        return self.calc_residual(self.params)

    @property
    def meas_angles(self) -> dict:
        """
        this property will return a dictionary
        of angles based on current instrument
        parameters.
        """
        angles_dict = {}
        for xray_source, rings in self.data.items():
            with switch_xray_source(self.instr, xray_source):
                ang_list = []
                for rng in rings:
                    ang_dict = dict.fromkeys(self.instr.detectors)
                    for det_name, meas_xy in rng.items():

                        panel = self.instr.detectors[det_name]
                        angles, _ = panel.cart_to_angles(
                                                    meas_xy,
                                                    tvec_s=self.instr.tvec,
                                                    apply_distortion=True)
                        ang_dict[det_name] = angles
                    ang_list.append(ang_dict)

            angles_dict[xray_source] = ang_list

        return angles_dict

    @property
    def tth_correction(self) -> dict:
        ret = {}
        for xray_source, rings in self.data.items():
            with switch_xray_source(self.instr, xray_source):
                corr_list = []
                for rng in rings:
                    corr_dict = dict.fromkeys(self.instr.detectors)
                    if self.tth_distortion is not None:
                        for det_name, meas_xy in rng.items():
                            # !!! sd has ref to detector so is updated
                            sd = self.tth_distortion[det_name]
                            tth_corr = sd.apply(meas_xy, return_nominal=False)[:, 0]
                            corr_dict[det_name] = tth_corr
                    corr_list.append(corr_dict)

            ret[xray_source] = corr_list

        return ret

    @property
    def two_XRS(self):
        return self.instr.has_multi_beam
