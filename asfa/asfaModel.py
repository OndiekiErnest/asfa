__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"


import pandas as pd
from PyQt5.QtCore import QSortFilterProxyModel, QModelIndex, QAbstractTableModel, Qt, QThread, pyqtSignal, pyqtSlot
import common
# from asfaWatcher import Watcher

models_logger = common.logging.getLogger(__name__)
models_logger.info(f">>> Initialized {__name__}")


class DataThread(QThread):
    """ populate data thread """
    __slots__ = ("data", "headers")

    result = pyqtSignal(object)

    def __init__(self, data, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTerminationEnabled(True)

        self.data = data

    @pyqtSlot()
    def run(self):

        rows = [row for generator in self.data for row in generator if row]
        self.result.emit(rows)

    def __del__(self):
        self.quit()
        self.wait()
        del self


class BaseModel(QAbstractTableModel):
    """ base model to inheriting from """

    BATCH_COUNT = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dataSource = pd.DataFrame()

        self.rows_loaded = self.BATCH_COUNT

    def rowCount(self, parent):
        # len(df.index) is faster than dataSource.shape
        rows = len(self.dataSource.index)
        if rows <= self.rows_loaded:
            return rows
        else:
            return self.rows_loaded

    def columnCount(self, parent):
        # len() is faster
        columns = len(self.dataSource.columns)
        return columns

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return str(self.dataSource.columns[section])

    def canFetchMore(self, index):
        """ if there is more data to be fetched return True """
        if len(self.dataSource.index) > self.rows_loaded:
            return True
        else:
            return False

    def fetchMore(self, index):
        """ get the next batch of data """
        remaining = len(self.dataSource.index) - self.rows_loaded
        to_fetch = min(remaining, self.BATCH_COUNT)
        # beginInsertRows(parent, start, end)
        # for a table (which is not hierarchical like Treeview), parent should be an invalid QModelIndex, meaning inserted items are at the root
        self.beginInsertRows(QModelIndex(), self.rows_loaded,
                             self.rows_loaded + to_fetch)
        self.rows_loaded += to_fetch
        self.endInsertRows()

    def _fallback_func(self, index):
        """ func to be called on undefined roles """
        return

    def _alignment_role(self, index):
        if index.column() in {2, 3}:
            return Qt.AlignCenter

    def setup(self, df):
        self.beginResetModel()
        self.dataSource = df
        self.endResetModel()


class SortFilterModel(QSortFilterProxyModel):
    """
    model for implementing search/sort feature
    """

    def sort(self, column, order):
        """ sort based on column and order """
        self.layoutAboutToBeChanged.emit()
        # use the source model sort function
        self.sourceModel().sort(column, order)

        self.layoutChanged.emit()

    def removeRows(self, selected: set):
        """ remove list of rows """
        # remove all rows from model before changing layout
        if selected:
            self.layoutAboutToBeChanged.emit()
            for name in selected:
                self.sourceModel().delete_name(name)
            self.layoutChanged.emit()


class ShareFilesModel(BaseModel):
    """
    custom share files model
    using a python pandas for storage
    it's notably fast in sorting,
    slower than python list in starting
    """

    def __init__(self, header: tuple, icons: dict, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.header = header
        self.icons = icons
        self.data_thread = DataThread(None)
        self.data_thread.result.connect(self._update_model)
        self.data_routes = {
            Qt.DisplayRole: self._display_role,
            Qt.UserRole: self._user_role,
            Qt.ToolTipRole: self._tooltip_role,
            Qt.DecorationRole: self._decoration_role,
            Qt.TextAlignmentRole: self._alignment_role,
        }

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return

        func = self.data_routes.get(role, self._fallback_func)
        return func(index)

    def _decoration_role(self, index):
        # decorate only the second column
        if index.column() == 1:
            value = self.dataSource.iloc[index.row(), index.column()]
            return self.icons.get(value, self.icons[0])

    def _tooltip_role(self, index):
        # get the tool tip for the 1st column
        if index.column() == 0:
            return self.dataSource.iloc[index.row(), index.column()]

    def _user_role(self, index):
        # get the whole row as a tuple
        return tuple(self.dataSource.iloc[index.row()])

    def _display_role(self, index):
        """ called for display role """
        # only icons to be displayed for the second col
        if index.column() == 1:
            return ""

        value = self.dataSource.iloc[index.row(), index.column()]
        if index.column() == 3:
            # convert to human readable
            return common.convert_bytes(value)
        return value

    def sort(self, col, order):
        """ sort table by given column number col """

        try:
            column = self.dataSource.columns[col]
            order = (order == Qt.AscendingOrder)
            models_logger.debug(
                f"Sort Share files, 'a' order: {order}, column: {col}")
            self.layoutAboutToBeChanged.emit()
            # sorting
            self.dataSource.sort_values(
                by=column, ascending=order, inplace=True)
            # done
            self.layoutChanged.emit()
        except IndexError:
            pass

    def _change_icon(self, name, code):
        """ change status code of `name` hence its icon """

        name = common._basename(name)
        row_filter = self.file_filter(name)
        # change the cell value to `code`
        try:
            index = self.dataSource.loc[row_filter].index.to_list()[0]
            self.dataSource.loc[row_filter, "Status"] = code
            # data changed on only a cell
            self.dataChanged.emit(self.index(index, 1), self.index(index, 1))
            models_logger.info(f"Changed icon code for '{name}'")
        except Exception as e:
            models_logger.error(f"Changing icon error: {e}")

    def file_filter(self, filename):
        """ filter based on filename """

        return self.dataSource["Name"] == filename

    def removeRows(self, selected: set):
        """ remove list of rows """
        # remove all rows from model before changing layout
        if selected:
            self.layoutAboutToBeChanged.emit()
            filt = self.file_filter
            for name in selected:
                self.dataSource.drop(index=self.dataSource[filt(
                    name)].index, inplace=True, errors="ignore")
                models_logger.debug(f"Share files model: dropped '{name}'")
            self.layoutChanged.emit()

    def setup_model(self, generator):
        """ create storage for our data """
        # if a thread is running, disconnect it from _update_model
        self.data_thread.result.disconnect()
        self.data_thread = DataThread((generator, ))
        self.data_thread.result.connect(self._update_model)
        self.data_thread.start()

    def _update_model(self, dataList):
        dataSource = pd.DataFrame(dataList, columns=self.header)
        dataSource = dataSource.astype(
            {"Status": "int8", "Type": "category", "Size": "category"})
        models_logger.debug("Share files model")
        self.setup(dataSource)


class DiskFilesModel(BaseModel):
    """
    custom disk files model
    using a python pandas for storage
    it's notably fast in sorting,
    slower than python list in starting
    """

    def __init__(self, generators, header, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers = header
        self.data_thread = DataThread(generators)
        self.data_thread.result.connect(self.update_model)
        self.data_thread.start()
        self.data_routes = {
            Qt.DisplayRole: self._display_role,
            Qt.UserRole: self._user_role,
            Qt.ToolTipRole: self._tooltip_role,
            Qt.TextAlignmentRole: self._alignment_role,
        }

        # self.files_watcher = Watcher(disk_path)
        # assign signals to slots
        # self.files_watcher.events.created.connect(self.append_row)
        # self.files_watcher.events.moved.connect(self.rename_row)
        # self.files_watcher.events.deleted.connect(self.delete_name)
        # start disk observer
        # self.files_watcher.observer_start()

    def data(self, index, role=Qt.DisplayRole):

        if not index.isValid():
            return

        func = self.data_routes.get(role, self._fallback_func)
        return func(index)

    def _tooltip_role(self, index):
        # get the tool tip for the 1st and 2nd column
        if index.column() in {0, 1}:
            return self.dataSource.iloc[index.row(), index.column()]

    def _user_role(self, index):
        # get the whole row
        return tuple(self.dataSource.iloc[index.row()])

    def _display_role(self, index):
        """ called for display role """
        value = self.dataSource.iloc[index.row(), index.column()]
        # convert size to human readable
        if index.column() == 3:
            return common.convert_bytes(value)
        return value

    def sort(self, col, order):
        """ sort table by given column number col """

        try:
            column = self.dataSource.columns[col]
            order = (order == Qt.AscendingOrder)
            models_logger.debug(
                f"Sort Disk files, 'a' order: {order}, column: {col}")
            # sorting
            self.dataSource.sort_values(
                by=column, ascending=order, inplace=True)
        except IndexError:
            pass

    def file_filter(self, filename):
        """ filter based on filename """

        name, dir_name = common._basename(
            filename), common.os.path.dirname(filename)
        return (self.dataSource["Name"] == name) & (self.dataSource["File Path"] == dir_name)

    def delete_name(self, name):
        """ delete filtered row """

        filt = self.file_filter(name)
        self.dataSource.drop(
            index=self.dataSource[filt].index, inplace=True, errors="ignore")
        models_logger.debug(f"Removed: '{name}'")

    # def append_row(self, name):
    #     """
    #     add new file to rows
    #     HONESTLY, this is what disqualifies pandas
    #     """

    #     print("APPENDING >>>", name)
    #     self.layoutAboutToBeChanged.emit()
    #     details = common.get_file_details(name)
    #     self.dataSource = self.dataSource.append(
    #         {"Name": details[0], "File Path": details[1], "Type": details[2], "Size": details[3]},
    #         ignore_index=True)
    #     self.layoutChanged.emit()

    # def rename_row(self, old, new):
    #     """ rename file """

    #     print("RENAMING >>>", old, new)
    #     self.layoutAboutToBeChanged.emit()
    #     filt = self.file_filter(old)
    #     details = common.get_file_details(new)
    #     self.dataSource.at[filt, ["Name", "File Path"]] = details[:2]
    #     self.layoutChanged.emit()

    def update_model(self, dataList):
        """ create storage for our data """

        models_logger.debug("Disk files model")

        dataSource = pd.DataFrame(dataList, columns=self.headers)
        dataSource = dataSource.astype(
            {"File Path": "category", "Type": "category"})
        self.setup(dataSource)
